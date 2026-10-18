"""Synthetic padding-boundary checks, executed only by the contained GPU worker."""
import ctypes as C
import hashlib
import math
import random
import secrets
import struct
import time


SHA_TEST_KERNEL = """
__kernel void test_sha512_short(__global const u8 *inputs,
                                __global const uint *lengths,
                                __global u8 *outputs, uint count) {
  size_t gid=get_global_id(0);
  if(gid>=count) return;
  u8 msg[128],digest[64];
  uint n=lengths[gid];
  for(uint i=0;i<n;++i) msg[i]=inputs[gid*128+i];
  crypto_hash(digest,msg,n);
  for(int i=0;i<64;++i) outputs[gid*64+i]=digest[i];
}
"""


def sha512_fixtures():
    rng=random.Random(0x51220261019)
    messages=[b'', b'abc']
    for n in range(114):
        messages.extend((bytes(n),bytes(range(n)),bytes(rng.randrange(256) for _ in range(n))))
    return messages


def check_sha512(source_path,backend,device_key,safe_check):
    """Compile the exact shipped source plus a SHA-only test entry point."""
    safe_check()
    cl=backend.OpenCL(device_key)
    try:
        original=source_path.read_bytes()
        source=original+SHA_TEST_KERNEL.encode('ascii')
        ptr=C.c_char_p(source);size=backend.SZ(len(source));err=backend.I()
        cl.program=cl.lib.clCreateProgramWithSource(cl.context,1,C.byref(ptr),C.byref(size),C.byref(err))
        cl.check(err.value)
        dev=backend.P(cl.device)
        ret=cl.lib.clBuildProgram(cl.program,1,C.byref(dev),b'-cl-std=CL1.2',None,None)
        if ret:
            n=backend.SZ()
            cl.lib.clGetProgramBuildInfo(cl.program,cl.device,0x1183,0,None,C.byref(n))
            log=C.create_string_buffer(n.value)
            cl.lib.clGetProgramBuildInfo(cl.program,cl.device,0x1183,n,log,None)
            raise RuntimeError(log.value.decode(errors='replace'))
        cl.kernel=cl.lib.clCreateKernel(cl.program,b'test_sha512_short',C.byref(err))
        cl.check(err.value)
        cap=backend.SZ()
        cl.check(cl.lib.clGetKernelWorkGroupInfo(cl.kernel,cl.device,0x11b0,C.sizeof(cap),C.byref(cap),None))
        limit=min(cap.value,cl.metadata['max_work_group'],cl.metadata['max_work_item_size_0'])
        local=next(v for v in (32,16,8,4,2,1) if v<=limit)
        messages=sha512_fixtures();count=len(messages)
        inbuf=cl.buffer(b''.join(message.ljust(128,b'\0') for message in messages))
        lenbuf=cl.buffer(struct.pack('<'+'I'*count,*(len(message) for message in messages)))
        outbuf=cl.buffer(size=count*64)
        args=[backend.P(inbuf),backend.P(lenbuf),backend.P(outbuf),backend.U(count)]
        for i,arg in enumerate(args):
            cl.check(cl.lib.clSetKernelArg(cl.kernel,i,C.sizeof(arg),C.byref(arg)))
        global_size=backend.SZ((count+local-1)//local*local);local_size=backend.SZ(local)
        out=C.create_string_buffer(count*64)
        safe_check()
        begin=time.perf_counter()
        cl.check(cl.lib.clEnqueueNDRangeKernel(cl.queue,cl.kernel,1,None,C.byref(global_size),C.byref(local_size),0,None,None))
        cl.check(cl.lib.clEnqueueReadBuffer(cl.queue,outbuf,1,0,count*64,out,0,None,None))
        elapsed=time.perf_counter()-begin
        safe_check()
        if not math.isfinite(elapsed) or elapsed<=0:
            raise RuntimeError('Invalid SHA-only dispatch timing')
        for i,message in enumerate(messages):
            if out.raw[i*64:(i+1)*64]!=hashlib.sha512(message).digest():
                raise RuntimeError('GPU SHA512 comparison failed for synthetic length '+str(len(message)))
        return {'passed':True,'cases':count,'lengths':list(range(114)),
                'patterns':['zero','incrementing','deterministic_random'],
                'empty_and_abc':True,'dispatch_seconds':elapsed,
                'kernel_sha256':hashlib.sha256(original).hexdigest()}
    finally:
        cl.close()


def check_prefix_boundaries(cl,oracle_factory,safe_check,local):
    """Exercise TAI message lengths111/112/113, including nonce carry/wrap."""
    count=32;start=(1<<64)-16;checked=0
    for length in (67,68,69):
        safe_check()
        oracle=oracle_factory(seed=secrets.token_bytes(32))
        try:
            prefix=bytes(range(length))
            cl.prepare(oracle.pubkey,oracle.scalar,prefix,count)
            output,_=cl.run(start,count,local_size=local)
            if len(output)!=count*64:
                raise RuntimeError('Incomplete GPU padding-boundary proof output')
            for i in range(count):
                alpha=prefix+((start+i)&((1<<64)-1)).to_bytes(8,'little')
                if output[i*64:(i+1)*64]!=oracle.evaluate(alpha):
                    raise RuntimeError('GPU padding-boundary proof comparison failed for prefix '+str(length))
                checked+=1
            safe_check()
        finally:
            oracle.close()
    return {'passed':True,'prefix_lengths':[67,68,69],'tai_message_lengths':[111,112,113],
            'official_proof_checks':checked,'nonce_carry_and_wrap':True}


def require_optimization_checks(checks,kernel_hash):
    """Do not grant validation when any optimized-hash coverage is incomplete."""
    sha=checks.get('sha512',{});boundary=checks.get('padding_boundaries',{})
    if (sha.get('passed') is not True or sha.get('cases')!=344 or
            sha.get('lengths')!=list(range(114)) or sha.get('empty_and_abc') is not True or
            sha.get('kernel_sha256')!=kernel_hash):
        raise RuntimeError('Complete source-bound SHA512 validation did not pass')
    if (boundary.get('passed') is not True or boundary.get('prefix_lengths')!=[67,68,69] or
            boundary.get('tai_message_lengths')!=[111,112,113] or
            boundary.get('official_proof_checks')!=96 or
            boundary.get('nonce_carry_and_wrap') is not True):
        raise RuntimeError('Complete official padding-boundary proof validation did not pass')
