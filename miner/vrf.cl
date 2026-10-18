// Derived from public-domain TweetNaCl, https://tweetnacl.cr.yp.to/
// Proxima ECVRF-EDWARDS25519-SHA512-TAI output search. No proof generation.
#define FOR(i,n) for (i=0;i<(n);++i)
#define sv static void
typedef uchar u8;
typedef uint u32;
typedef ulong u64;
typedef long i64;
typedef int gf[10];
static u64 dl64(const u8 *x)
{
  u64 i,u=0;
  FOR(i,8) u=(u<<8)|x[i];
  return u;
}

sv ts64(u8 *x,u64 u)
{
  int i;
  for (i = 7;i >= 0;--i) { x[i] = u; u >>= 8; }
}

static int vn(const u8 *x,const u8 *y,int n)
{
  u32 i,d = 0;
  FOR(i,n) d |= x[i]^y[i];
  return (1 & ((d - 1) >> 8)) - 1;
}

int crypto_verify_16(const u8 *x,const u8 *y)
{
  return vn(x,y,16);
}

int crypto_verify_32(const u8 *x,const u8 *y)
{
  return vn(x,y,32);
}

sv set25519(gf r,const gf a){for(int i=0;i<10;i++){r[i]=a[i];}}

sv car25519(gf t) {
int c;
c=t[0]>>26;
t[0]-=c*67108864;
t[1]+=c;
c=t[1]>>25;
t[1]-=c*33554432;
t[2]+=c;
c=t[2]>>26;
t[2]-=c*67108864;
t[3]+=c;
c=t[3]>>25;
t[3]-=c*33554432;
t[4]+=c;
c=t[4]>>26;
t[4]-=c*67108864;
t[5]+=c;
c=t[5]>>25;
t[5]-=c*33554432;
t[6]+=c;
c=t[6]>>26;
t[6]-=c*67108864;
t[7]+=c;
c=t[7]>>25;
t[7]-=c*33554432;
t[8]+=c;
c=t[8]>>26;
t[8]-=c*67108864;
t[9]+=c;
c=t[9]>>25;
t[9]-=c*33554432;
t[0]+=19*c;
}

sv sel25519(gf p,gf q,int b){int c=~(b-1); for(int i=0;i<10;i++){int t=c&(p[i]^q[i]); p[i]^=t;q[i]^=t;}}

sv pack25519(u8 *o,const gf in){gf t,m;
set25519(t,in);car25519(t);car25519(t);car25519(t);
for(int trial=0;trial<2;trial++){
m[0]=t[0]-67108845;
m[1]=t[1]-33554431-((m[0]>>26)&1);
m[0]&=67108863;
m[2]=t[2]-67108863-((m[1]>>25)&1);
m[1]&=33554431;
m[3]=t[3]-33554431-((m[2]>>26)&1);
m[2]&=67108863;
m[4]=t[4]-67108863-((m[3]>>25)&1);
m[3]&=33554431;
m[5]=t[5]-33554431-((m[4]>>26)&1);
m[4]&=67108863;
m[6]=t[6]-67108863-((m[5]>>25)&1);
m[5]&=33554431;
m[7]=t[7]-33554431-((m[6]>>26)&1);
m[6]&=67108863;
m[8]=t[8]-67108863-((m[7]>>25)&1);
m[7]&=33554431;
m[9]=t[9]-33554431-((m[8]>>26)&1);
m[8]&=67108863;
int borrow=(m[9]>>25)&1;
m[9]&=33554431;
sel25519(t,m,1-borrow);
}
o[0]=(u8)(((uint)t[0]>>0));
o[1]=(u8)(((uint)t[0]>>8));
o[2]=(u8)(((uint)t[0]>>16));
o[3]=(u8)(((uint)t[0]>>24)|((uint)t[1]<<2));
o[4]=(u8)(((uint)t[1]>>6));
o[5]=(u8)(((uint)t[1]>>14));
o[6]=(u8)(((uint)t[1]>>22)|((uint)t[2]<<3));
o[7]=(u8)(((uint)t[2]>>5));
o[8]=(u8)(((uint)t[2]>>13));
o[9]=(u8)(((uint)t[2]>>21)|((uint)t[3]<<5));
o[10]=(u8)(((uint)t[3]>>3));
o[11]=(u8)(((uint)t[3]>>11));
o[12]=(u8)(((uint)t[3]>>19)|((uint)t[4]<<6));
o[13]=(u8)(((uint)t[4]>>2));
o[14]=(u8)(((uint)t[4]>>10));
o[15]=(u8)(((uint)t[4]>>18));
o[16]=(u8)(((uint)t[5]>>0));
o[17]=(u8)(((uint)t[5]>>8));
o[18]=(u8)(((uint)t[5]>>16));
o[19]=(u8)(((uint)t[5]>>24)|((uint)t[6]<<1));
o[20]=(u8)(((uint)t[6]>>7));
o[21]=(u8)(((uint)t[6]>>15));
o[22]=(u8)(((uint)t[6]>>23)|((uint)t[7]<<3));
o[23]=(u8)(((uint)t[7]>>5));
o[24]=(u8)(((uint)t[7]>>13));
o[25]=(u8)(((uint)t[7]>>21)|((uint)t[8]<<4));
o[26]=(u8)(((uint)t[8]>>4));
o[27]=(u8)(((uint)t[8]>>12));
o[28]=(u8)(((uint)t[8]>>20)|((uint)t[9]<<6));
o[29]=(u8)(((uint)t[9]>>2));
o[30]=(u8)(((uint)t[9]>>10));
o[31]=(u8)(((uint)t[9]>>18));
}

static int neq25519(const gf a, const gf b)
{
  u8 c[32],d[32];
  pack25519(c,a);
  pack25519(d,b);
  return crypto_verify_32(c,d);
}

static u8 par25519(const gf a)
{
  u8 d[32];
  pack25519(d,a);
  return d[0]&1;
}

sv unpack25519(gf o,const u8 *in){
o[0]=(int)((((uint)in[0]<<0)|((uint)in[1]<<8)|((uint)in[2]<<16)|((uint)in[3]<<24))&67108863u);
o[1]=(int)((((uint)in[3]>>2)|((uint)in[4]<<6)|((uint)in[5]<<14)|((uint)in[6]<<22))&33554431u);
o[2]=(int)((((uint)in[6]>>3)|((uint)in[7]<<5)|((uint)in[8]<<13)|((uint)in[9]<<21))&67108863u);
o[3]=(int)((((uint)in[9]>>5)|((uint)in[10]<<3)|((uint)in[11]<<11)|((uint)in[12]<<19))&33554431u);
o[4]=(int)((((uint)in[12]>>6)|((uint)in[13]<<2)|((uint)in[14]<<10)|((uint)in[15]<<18))&67108863u);
o[5]=(int)((((uint)in[16]<<0)|((uint)in[17]<<8)|((uint)in[18]<<16)|((uint)in[19]<<24))&33554431u);
o[6]=(int)((((uint)in[19]>>1)|((uint)in[20]<<7)|((uint)in[21]<<15)|((uint)in[22]<<23))&67108863u);
o[7]=(int)((((uint)in[22]>>3)|((uint)in[23]<<5)|((uint)in[24]<<13)|((uint)in[25]<<21))&33554431u);
o[8]=(int)((((uint)in[25]>>4)|((uint)in[26]<<4)|((uint)in[27]<<12)|((uint)in[28]<<20))&67108863u);
o[9]=(int)((((uint)in[28]>>6)|((uint)in[29]<<2)|((uint)in[30]<<10)|((uint)in[31]<<18))&33554431u);
}

sv A(gf o,const gf a,const gf b){for(int i=0;i<10;i++){o[i]=a[i]+b[i];}}

sv Z(gf o,const gf a,const gf b){for(int i=0;i<10;i++){o[i]=a[i]-b[i];}}

// Alternating 26/25-bit limbs; fold powers of 2^255 using 2^255 = 19.
// M/S input bound: abs(limb[i]) <= 4 * 2^width[i] + 128.
// The largest coefficient is <= 8971182277476401152 < INT64_MAX.
// Keep this bound when changing the field-operation call graph.
// Exact radix-65536 carry, wide until both passes are finished.
sv field_carry_wide(i64 t[10]) {
i64 c;
c=t[0]>>26;
t[0]-=c*67108864L;
t[1]+=c;
c=t[1]>>25;
t[1]-=c*33554432L;
t[2]+=c;
c=t[2]>>26;
t[2]-=c*67108864L;
t[3]+=c;
c=t[3]>>25;
t[3]-=c*33554432L;
t[4]+=c;
c=t[4]>>26;
t[4]-=c*67108864L;
t[5]+=c;
c=t[5]>>25;
t[5]-=c*33554432L;
t[6]+=c;
c=t[6]>>26;
t[6]-=c*67108864L;
t[7]+=c;
c=t[7]>>25;
t[7]-=c*33554432L;
t[8]+=c;
c=t[8]>>26;
t[8]-=c*67108864L;
t[9]+=c;
c=t[9]>>25;
t[9]-=c*33554432L;
t[0]+=19*c;
}

sv M(gf o,const gf a,const gf b) {
i64 t[10];
t[0]=((i64)a[0]*b[0])+38*((i64)a[1]*b[9])+19*((i64)a[2]*b[8])+38*((i64)a[3]*b[7])+19*((i64)a[4]*b[6])+38*((i64)a[5]*b[5])+19*((i64)a[6]*b[4])+38*((i64)a[7]*b[3])+19*((i64)a[8]*b[2])+38*((i64)a[9]*b[1]);
t[1]=((i64)a[0]*b[1])+((i64)a[1]*b[0])+19*((i64)a[2]*b[9])+19*((i64)a[3]*b[8])+19*((i64)a[4]*b[7])+19*((i64)a[5]*b[6])+19*((i64)a[6]*b[5])+19*((i64)a[7]*b[4])+19*((i64)a[8]*b[3])+19*((i64)a[9]*b[2]);
t[2]=((i64)a[0]*b[2])+2*((i64)a[1]*b[1])+((i64)a[2]*b[0])+38*((i64)a[3]*b[9])+19*((i64)a[4]*b[8])+38*((i64)a[5]*b[7])+19*((i64)a[6]*b[6])+38*((i64)a[7]*b[5])+19*((i64)a[8]*b[4])+38*((i64)a[9]*b[3]);
t[3]=((i64)a[0]*b[3])+((i64)a[1]*b[2])+((i64)a[2]*b[1])+((i64)a[3]*b[0])+19*((i64)a[4]*b[9])+19*((i64)a[5]*b[8])+19*((i64)a[6]*b[7])+19*((i64)a[7]*b[6])+19*((i64)a[8]*b[5])+19*((i64)a[9]*b[4]);
t[4]=((i64)a[0]*b[4])+2*((i64)a[1]*b[3])+((i64)a[2]*b[2])+2*((i64)a[3]*b[1])+((i64)a[4]*b[0])+38*((i64)a[5]*b[9])+19*((i64)a[6]*b[8])+38*((i64)a[7]*b[7])+19*((i64)a[8]*b[6])+38*((i64)a[9]*b[5]);
t[5]=((i64)a[0]*b[5])+((i64)a[1]*b[4])+((i64)a[2]*b[3])+((i64)a[3]*b[2])+((i64)a[4]*b[1])+((i64)a[5]*b[0])+19*((i64)a[6]*b[9])+19*((i64)a[7]*b[8])+19*((i64)a[8]*b[7])+19*((i64)a[9]*b[6]);
t[6]=((i64)a[0]*b[6])+2*((i64)a[1]*b[5])+((i64)a[2]*b[4])+2*((i64)a[3]*b[3])+((i64)a[4]*b[2])+2*((i64)a[5]*b[1])+((i64)a[6]*b[0])+38*((i64)a[7]*b[9])+19*((i64)a[8]*b[8])+38*((i64)a[9]*b[7]);
t[7]=((i64)a[0]*b[7])+((i64)a[1]*b[6])+((i64)a[2]*b[5])+((i64)a[3]*b[4])+((i64)a[4]*b[3])+((i64)a[5]*b[2])+((i64)a[6]*b[1])+((i64)a[7]*b[0])+19*((i64)a[8]*b[9])+19*((i64)a[9]*b[8]);
t[8]=((i64)a[0]*b[8])+2*((i64)a[1]*b[7])+((i64)a[2]*b[6])+2*((i64)a[3]*b[5])+((i64)a[4]*b[4])+2*((i64)a[5]*b[3])+((i64)a[6]*b[2])+2*((i64)a[7]*b[1])+((i64)a[8]*b[0])+38*((i64)a[9]*b[9]);
t[9]=((i64)a[0]*b[9])+((i64)a[1]*b[8])+((i64)a[2]*b[7])+((i64)a[3]*b[6])+((i64)a[4]*b[5])+((i64)a[5]*b[4])+((i64)a[6]*b[3])+((i64)a[7]*b[2])+((i64)a[8]*b[1])+((i64)a[9]*b[0]);
field_carry_wide(t);
field_carry_wide(t);
o[0]=(int)t[0];
o[1]=(int)t[1];
o[2]=(int)t[2];
o[3]=(int)t[3];
o[4]=(int)t[4];
o[5]=(int)t[5];
o[6]=(int)t[6];
o[7]=(int)t[7];
o[8]=(int)t[8];
o[9]=(int)t[9];
}

sv S(gf o,const gf a) {
i64 t[10];
t[0]=((i64)a[0]*a[0])+76*((i64)a[1]*a[9])+38*((i64)a[2]*a[8])+76*((i64)a[3]*a[7])+38*((i64)a[4]*a[6])+38*((i64)a[5]*a[5]);
t[1]=2*((i64)a[0]*a[1])+38*((i64)a[2]*a[9])+38*((i64)a[3]*a[8])+38*((i64)a[4]*a[7])+38*((i64)a[5]*a[6]);
t[2]=2*((i64)a[0]*a[2])+2*((i64)a[1]*a[1])+76*((i64)a[3]*a[9])+38*((i64)a[4]*a[8])+76*((i64)a[5]*a[7])+19*((i64)a[6]*a[6]);
t[3]=2*((i64)a[0]*a[3])+2*((i64)a[1]*a[2])+38*((i64)a[4]*a[9])+38*((i64)a[5]*a[8])+38*((i64)a[6]*a[7]);
t[4]=2*((i64)a[0]*a[4])+4*((i64)a[1]*a[3])+((i64)a[2]*a[2])+76*((i64)a[5]*a[9])+38*((i64)a[6]*a[8])+38*((i64)a[7]*a[7]);
t[5]=2*((i64)a[0]*a[5])+2*((i64)a[1]*a[4])+2*((i64)a[2]*a[3])+38*((i64)a[6]*a[9])+38*((i64)a[7]*a[8]);
t[6]=2*((i64)a[0]*a[6])+4*((i64)a[1]*a[5])+2*((i64)a[2]*a[4])+2*((i64)a[3]*a[3])+76*((i64)a[7]*a[9])+19*((i64)a[8]*a[8]);
t[7]=2*((i64)a[0]*a[7])+2*((i64)a[1]*a[6])+2*((i64)a[2]*a[5])+2*((i64)a[3]*a[4])+38*((i64)a[8]*a[9]);
t[8]=2*((i64)a[0]*a[8])+4*((i64)a[1]*a[7])+2*((i64)a[2]*a[6])+4*((i64)a[3]*a[5])+((i64)a[4]*a[4])+38*((i64)a[9]*a[9]);
t[9]=2*((i64)a[0]*a[9])+2*((i64)a[1]*a[8])+2*((i64)a[2]*a[7])+2*((i64)a[3]*a[6])+2*((i64)a[4]*a[5]);
field_carry_wide(t);
field_carry_wide(t);
o[0]=(int)t[0];
o[1]=(int)t[1];
o[2]=(int)t[2];
o[3]=(int)t[3];
o[4]=(int)t[4];
o[5]=(int)t[5];
o[6]=(int)t[6];
o[7]=(int)t[7];
o[8]=(int)t[8];
o[9]=(int)t[9];
}

// Fixed addition chain: z^(2^250-1), retaining z^11 for inversion.
sv square_n(gf o,const gf z,int count)
{
  set25519(o,z);
  for(int j=0;j<count;++j) S(o,o);
}

sv pow250(gf o,gf z11,const gf z)
{
  gf t1,t2,t3;
  S(z11,z);
  S(t1,z11);
  S(t1,t1);
  M(t1,z,t1);
  M(z11,z11,t1);
  S(t2,z11);
  M(t1,t1,t2);             // 2^5-1
  square_n(t2,t1,5);
  M(t1,t2,t1);             // 2^10-1
  square_n(t2,t1,10);
  M(t2,t2,t1);             // 2^20-1
  square_n(t3,t2,20);
  M(t2,t3,t2);             // 2^40-1
  square_n(t2,t2,10);
  M(t1,t2,t1);             // 2^50-1
  square_n(t2,t1,50);
  M(t2,t2,t1);             // 2^100-1
  square_n(t3,t2,100);
  M(t2,t3,t2);             // 2^200-1
  square_n(t2,t2,50);
  M(o,t2,t1);              // 2^250-1
}

sv inv25519(gf o,const gf z)
{
  gf t,z11;
  pow250(t,z11,z);
  square_n(t,t,5);
  M(o,t,z11);              // 2^255-21 = p-2
}

sv pow2523(gf o,const gf z)
{
  gf t,z11;
  pow250(t,z11,z);
  square_n(t,t,2);
  M(o,t,z);                // 2^252-3
}

static u64 R(u64 x,int c) { return (x >> c) | (x << (64 - c)); }
static u64 Ch(u64 x,u64 y,u64 z) { return (x & y) ^ (~x & z); }
static u64 Maj(u64 x,u64 y,u64 z) { return (x & y) ^ (x & z) ^ (y & z); }
static u64 Sigma0(u64 x) { return R(x,28) ^ R(x,34) ^ R(x,39); }
static u64 Sigma1(u64 x) { return R(x,14) ^ R(x,18) ^ R(x,41); }
static u64 sigma0(u64 x) { return R(x, 1) ^ R(x, 8) ^ (x >> 7); }
static u64 sigma1(u64 x) { return R(x,19) ^ R(x,61) ^ (x >> 6); }

__constant u64 K[80] = 
{
  0x428a2f98d728ae22ULL, 0x7137449123ef65cdULL, 0xb5c0fbcfec4d3b2fULL, 0xe9b5dba58189dbbcULL,
  0x3956c25bf348b538ULL, 0x59f111f1b605d019ULL, 0x923f82a4af194f9bULL, 0xab1c5ed5da6d8118ULL,
  0xd807aa98a3030242ULL, 0x12835b0145706fbeULL, 0x243185be4ee4b28cULL, 0x550c7dc3d5ffb4e2ULL,
  0x72be5d74f27b896fULL, 0x80deb1fe3b1696b1ULL, 0x9bdc06a725c71235ULL, 0xc19bf174cf692694ULL,
  0xe49b69c19ef14ad2ULL, 0xefbe4786384f25e3ULL, 0x0fc19dc68b8cd5b5ULL, 0x240ca1cc77ac9c65ULL,
  0x2de92c6f592b0275ULL, 0x4a7484aa6ea6e483ULL, 0x5cb0a9dcbd41fbd4ULL, 0x76f988da831153b5ULL,
  0x983e5152ee66dfabULL, 0xa831c66d2db43210ULL, 0xb00327c898fb213fULL, 0xbf597fc7beef0ee4ULL,
  0xc6e00bf33da88fc2ULL, 0xd5a79147930aa725ULL, 0x06ca6351e003826fULL, 0x142929670a0e6e70ULL,
  0x27b70a8546d22ffcULL, 0x2e1b21385c26c926ULL, 0x4d2c6dfc5ac42aedULL, 0x53380d139d95b3dfULL,
  0x650a73548baf63deULL, 0x766a0abb3c77b2a8ULL, 0x81c2c92e47edaee6ULL, 0x92722c851482353bULL,
  0xa2bfe8a14cf10364ULL, 0xa81a664bbc423001ULL, 0xc24b8b70d0f89791ULL, 0xc76c51a30654be30ULL,
  0xd192e819d6ef5218ULL, 0xd69906245565a910ULL, 0xf40e35855771202aULL, 0x106aa07032bbd1b8ULL,
  0x19a4c116b8d2d0c8ULL, 0x1e376c085141ab53ULL, 0x2748774cdf8eeb99ULL, 0x34b0bcb5e19b48a8ULL,
  0x391c0cb3c5c95a63ULL, 0x4ed8aa4ae3418acbULL, 0x5b9cca4f7763e373ULL, 0x682e6ff3d6b2b8a3ULL,
  0x748f82ee5defb2fcULL, 0x78a5636f43172f60ULL, 0x84c87814a1f0ab72ULL, 0x8cc702081a6439ecULL,
  0x90befffa23631e28ULL, 0xa4506cebde82bde9ULL, 0xbef9a3f7b2c67915ULL, 0xc67178f2e372532bULL,
  0xca273eceea26619cULL, 0xd186b8c721c0c207ULL, 0xeada7dd6cde0eb1eULL, 0xf57d4f7fee6ed178ULL,
  0x06f067aa72176fbaULL, 0x0a637dc5a2c898a6ULL, 0x113f9804bef90daeULL, 0x1b710b35131c471bULL,
  0x28db77f523047d84ULL, 0x32caab7b40c72493ULL, 0x3c9ebe0a15c9bebcULL, 0x431d67c49c100d4cULL,
  0x4cc5d4becb3e42b6ULL, 0x597f299cfc657e2aULL, 0x5fcb6fab3ad6faecULL, 0x6c44198c4a475817ULL
};

int crypto_hashblocks(u8 *x,const u8 *m,u64 n)
{
  u64 z[8],b[8],a[8],w[16],t;
  int i,j;

  FOR(i,8) z[i] = a[i] = dl64(x + 8 * i);

  while (n >= 128) {
    FOR(i,16) w[i] = dl64(m + 8 * i);

    FOR(i,80) {
      FOR(j,8) b[j] = a[j];
      t = a[7] + Sigma1(a[4]) + Ch(a[4],a[5],a[6]) + K[i] + w[i%16];
      b[7] = t + Sigma0(a[0]) + Maj(a[0],a[1],a[2]);
      b[3] += t;
      FOR(j,8) a[(j+1)%8] = b[j];
      if (i%16 == 15)
	FOR(j,16)
	  w[j] += w[(j+9)%16] + sigma0(w[(j+1)%16]) + sigma1(w[(j+14)%16]);
    }

    FOR(i,8) { a[i] += z[i]; z[i] = a[i]; }

    m += 128;
    n -= 128;
  }

  FOR(i,8) ts64(x+8*i,z[i]);

  return n;
}

__constant u8 iv[64] = {
  0x6a,0x09,0xe6,0x67,0xf3,0xbc,0xc9,0x08,
  0xbb,0x67,0xae,0x85,0x84,0xca,0xa7,0x3b,
  0x3c,0x6e,0xf3,0x72,0xfe,0x94,0xf8,0x2b,
  0xa5,0x4f,0xf5,0x3a,0x5f,0x1d,0x36,0xf1,
  0x51,0x0e,0x52,0x7f,0xad,0xe6,0x82,0xd1,
  0x9b,0x05,0x68,0x8c,0x2b,0x3e,0x6c,0x1f,
  0x1f,0x83,0xd9,0xab,0xfb,0x41,0xbd,0x6b,
  0x5b,0xe0,0xcd,0x19,0x13,0x7e,0x21,0x79
} ;

// Specialized for the kernel's 35-byte / <=113-byte messages.
int crypto_hash(u8 *out,const u8 *m,u64 n)
{
  u8 h[64],x[128];
  for(int i=0;i<64;++i) h[i]=iv[i];
  for(int i=0;i<128;++i) x[i]=0;
  for(uint i=0;i<(uint)n;++i) x[i]=m[i];
  x[n]=128;
  if(n>=112) {
    crypto_hashblocks(h,x,128);
    for(int i=0;i<128;++i) x[i]=0;
  }
  ts64(x+120,n<<3);
  crypto_hashblocks(h,x,128);
  for(int i=0;i<64;++i) out[i]=h[i];
  return 0;
}


sv add(gf p[4],gf q[4])
{
  const gf D2={0x2b2f159,0x1a6e509,0x22add7a,0xd4141d,0x38052,0xf3d130,0x3407977,0x19ce331,0x1c56dff,0x901b67};

  gf a,b,c,d,t,e,f,g,h;
  
  Z(a, p[1], p[0]);
  Z(t, q[1], q[0]);
  M(a, a, t);
  A(b, p[0], p[1]);
  A(t, q[0], q[1]);
  M(b, b, t);
  M(c, p[3], q[3]);
  M(c, c, D2);
  M(d, p[2], q[2]);
  A(d, d, d);
  Z(e, b, a);
  Z(f, d, c);
  A(g, d, c);
  A(h, b, a);

  M(p[0], e, f);
  M(p[1], h, g);
  M(p[2], g, f);
  M(p[3], e, h);
}

sv cswap(gf p[4],gf q[4],u8 b)
{
  int i;
  FOR(i,4)
    sel25519(p[i],q[i],b);
}

sv pack(u8 *r,gf p[4])
{
  gf tx, ty, zi;
  inv25519(zi, p[2]); 
  M(tx, p[0], zi);
  M(ty, p[1], zi);
  pack25519(r, ty);
  r[31] ^= par25519(tx) << 7;
}


// Extended Edwards coordinates, a=-1: 4M+4S (dbl-2008-hwcd).
sv point_double(gf p[4])
{
  const gf zero={0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};
  gf a,b,c,e,f,g,h;
  S(a,p[0]);
  S(b,p[1]);
  S(c,p[2]);
  A(c,c,c);
  A(e,p[0],p[1]);
  S(e,e);
  Z(e,e,a);
  Z(e,e,b);
  Z(g,b,a);
  Z(f,g,c);
  A(h,a,b);
  Z(h,zero,h);
  M(p[0],e,f);
  M(p[1],g,h);
  M(p[2],f,g);
  M(p[3],e,h);
}

// Destructive private point cache: (Y-X, Y+X, 2Z, 2dT).
sv point_cache(gf q[4])
{
  const gf D2={0x2b2f159,0x1a6e509,0x22add7a,0xd4141d,0x38052,0xf3d130,0x3407977,0x19ce331,0x1c56dff,0x901b67};
  gf x;
  set25519(x,q[0]);
  Z(q[0],q[1],x);
  A(q[1],q[1],x);
  A(q[2],q[2],q[2]);
  M(q[3],q[3],D2);
}

// Complete Edwards addition with a cached point, eight field multiplies.
// A negative signed digit negates X and T, swapping cached Y-X / Y+X.
sv add_cached(gf p[4],gf q[4],int negative)
{
  gf a,b,c,d,e,f,g,h;
  Z(a,p[1],p[0]);
  A(b,p[1],p[0]);
  if(negative) {
    M(a,a,q[1]);
    M(b,b,q[0]);
  } else {
    M(a,a,q[0]);
    M(b,b,q[1]);
  }
  M(c,p[3],q[3]);
  M(d,p[2],q[2]);
  Z(e,b,a);
  A(h,b,a);
  if(negative) {
    A(f,d,c);
    Z(g,d,c);
  } else {
    Z(f,d,c);
    A(g,d,c);
  }
  M(p[0],e,f);
  M(p[1],h,g);
  M(p[2],g,f);
  M(p[3],e,h);
}

sv scalarmult(gf p[4],gf q[4],const u8 *s)
{

  const gf gf0={0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};
  const gf gf1={0x1,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};
  set25519(p[0],gf0);
  set25519(p[1],gf1);
  set25519(p[2],gf1);
  set25519(p[3],gf0);

  // Exact width-2 NAF: d_i = bit(3s,i+1) - bit(s,i+1).
  // The extra byte retains the carry for arbitrary 256-bit scalar inputs.
  u8 triple[33];
  uint carry=0;
  for(int i=0;i<32;++i) {
    uint v=3*(uint)s[i]+carry;
    triple[i]=(u8)v;
    carry=v>>8;
  }
  triple[32]=(u8)carry;
  point_cache(q);
  for(int i=256;i>=0;--i) {
    int pos=i+1;
    int digit=((triple[pos/8]>>(pos&7))&1);
    if(pos<256) digit-=((s[pos/8]>>(pos&7))&1);
    point_double(p);
    if(digit) add_cached(p,q,digit<0);
  }
}

sv scalarbase(gf p[4],const u8 *s)
{
  const gf X={0x325d51a,0x18b5823,0xf6592a,0x104a92d,0x1a4b31d,0x1d6dc5c,0x27118fe,0x7fd814,0x13cd6e5,0x85a4db};
  const gf Y={0x2666658,0x1999999,0xcccccc,0x1333333,0x1999999,0x666666,0x3333333,0xcccccc,0x2666666,0x1999999};
  const gf gf1={0x1,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};

  gf q[4];
  set25519(q[0],X);
  set25519(q[1],Y);
  set25519(q[2],gf1);
  M(q[3],X,Y);
  scalarmult(p,q,s);
}

static int unpackneg(gf r[4],const u8 p[32])
{
  const gf gf0={0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};
  const gf gf1={0x1,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};
  const gf D={0x35978a3,0xd37284,0x3156ebd,0x6a0a0e,0x1c029,0x179e898,0x3a03cbb,0x1ce7198,0x2e2b6ff,0x1480db3};
  const gf I={0x20ea0b0,0x186c9d2,0x8f189d,0x35697f,0xbd0c60,0x1fbd7a7,0x2804c9e,0x1e16569,0x4fc1d,0xae0c92};

  gf t, chk, num, den, den2, den4, den6;
  set25519(r[2],gf1);
  unpack25519(r[1],p);
  S(num,r[1]);
  M(den,num,D);
  Z(num,num,r[2]);
  A(den,r[2],den);

  S(den2,den);
  S(den4,den2);
  M(den6,den4,den2);
  M(t,den6,num);
  M(t,t,den);

  pow2523(t,t);
  M(t,t,num);
  M(t,t,den);
  M(t,t,den);
  M(r[0],t,den);

  S(chk,r[0]);
  M(chk,chk,den);
  if (neq25519(chk, num)) M(r[0],r[0],I);

  S(chk,r[0]);
  M(chk,chk,den);
  if (neq25519(chk, num)) return -1;

  if (par25519(r[0]) != (p[31]>>7)) Z(r[0],gf0,r[0]);

  M(r[3],r[0],r[1]);
  return 0;
}



// The leading nonzero NAF digit of an unsigned scalar is +1. Starting at Q
// avoids doubling the identity and adding the first Q; zero retains identity.
sv scalarmult_shared_naf(gf p[4],gf q[4],__local const char *naf,
                         __local const int *naf_top)
{
  const gf gf0={0};
  const gf gf1={1};
  int top=naf_top[0];
  if(top<0) {
    set25519(p[0],gf0); set25519(p[1],gf1);
    set25519(p[2],gf1); set25519(p[3],gf0);
    return;
  }
  for(int j=0;j<4;++j) set25519(p[j],q[j]);
  point_cache(q);
  for(int i=top-1;i>=0;--i) {
    int digit=(int)naf[i];
    point_double(p);
    if(digit) add_cached(p,q,digit<0);
  }
}

// Single work item = full VRF evaluation. Scalar is uploaded as a runtime buffer.
__kernel void vrf_batch(__global const u8 *pubkey, __global const u8 *scalar,
                        __global const u8 *prefix, uint prefix_len,
                        ulong start, uint with_nonce, __global u8 *outputs) {
  size_t gid = get_global_id(0);

  __local char shared_naf[257];
  __local int shared_naf_top[1];
  if(get_local_id(0)==0) {
    uint carry=0;
    for(int j=0;j<32;++j) {
      uint sj=(uint)scalar[j], v=3*sj+carry;
      carry=v>>8;
      for(int b=0;b<8;++b) {
        int pos=j*8+b;
        if(pos) shared_naf[pos-1]=(char)((int)((v>>b)&1)-(int)((sj>>b)&1));
      }
    }
    shared_naf[255]=(char)(carry&1);
    shared_naf[256]=(char)((carry>>1)&1);
    int top=256;
    while(top>=0 && shared_naf[top]==0) --top;
    shared_naf_top[0]=top;
  }
  // All work items reach this barrier, before any divergent search or return.
  barrier(CLK_LOCAL_MEM_FENCE);

  u8 msg[128], digest[64], beta_msg[35], encoded[32];
  gf h[4], gamma[4];
  const gf gf0={0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0};
  msg[0]=3; msg[1]=1;
  for(int i=0;i<32;i++) msg[2+i]=pubkey[i];
  for(uint i=0;i<prefix_len;i++)msg[34+i]=prefix[i];
  uint n=34+prefix_len;
  if(with_nonce){ulong nonce=start+(ulong)gid; for(int i=0;i<8;i++)msg[n+i]=(nonce>>(i*8))&255; n+=8;}
  msg[n+1]=0;
  int valid=0;
  for(int ctr=0;ctr<256;ctr++){
    msg[n]=(u8)ctr; crypto_hash(digest,msg,n+2);
    if(unpackneg(h,digest))continue;
    point_double(h); point_double(h); point_double(h); // encode_to_curve cofactor
    // Identity check without inversion: X == 0 and Y == Z.
    if(!neq25519(h[0],gf0) && !neq25519(h[1],h[2]))continue;
    valid=1; break;
  }
  if(!valid){for(int i=0;i<64;i++)outputs[gid*64+i]=0xff;return;}
  scalarmult_shared_naf(gamma,h,shared_naf,shared_naf_top);
  point_double(gamma); point_double(gamma); point_double(gamma); // proof_to_hash cofactor
  pack(encoded,gamma);
  beta_msg[0]=3; beta_msg[1]=3;
  for(int i=0;i<32;i++)beta_msg[2+i]=encoded[i];
  beta_msg[34]=0; crypto_hash(digest,beta_msg,35);
  for(int i=0;i<64;i++)outputs[gid*64+i]=digest[i];
}
