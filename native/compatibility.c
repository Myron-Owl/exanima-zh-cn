/* Strict relocation-only compatibility detection. This module never writes executable memory. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "compatibility.h"
#include "compatibility_contract.h"

#define MAX_SECTIONS 32
#define MAX_CANDIDATES 128
#define MAX_REFS 512
#define FLAGS 0xe0000000u
#define EXECUTE 0x20000000u
#define READABLE 0x40000000u
typedef struct { unsigned char name[8]; uint32_t rva,size,raw,raw_size,flags; } Section;
typedef struct {
    const unsigned char *data; size_t size; uint32_t image_size,section_count,pdata,pdata_size;
    uint64_t preferred_base; Section sections[MAX_SECTIONS];
} Image;
typedef struct { uint32_t offset,size,end; int32_t role; uint32_t old_target,flags,literal_length; const unsigned char *literal_hash; } Reference;
typedef struct {
    uint32_t old_rva,length,pdata,copy_size,anchor_size,ref_count;
    const unsigned char *hash,*anchor;
    Reference *refs;
    uint32_t candidates[MAX_CANDIDATES],candidate_count,found;
} Function;
typedef struct { uint32_t legacy,length,radius; const unsigned char *hash,*text; } Scope;
typedef struct { const unsigned char *data; size_t size,pos; } Reader;
typedef struct { uint32_t old_target,new_target; } Identity;

static uint32_t u32(const unsigned char *p) { uint32_t v;memcpy(&v,p,4);return v; }
static uint64_t u64(const unsigned char *p) { uint64_t v;memcpy(&v,p,8);return v; }
static uint16_t u16(const unsigned char *p) { uint16_t v;memcpy(&v,p,2);return v; }
static BOOL bounds(size_t total,size_t offset,size_t length) { return offset<=total && length<=total-offset; }
static BOOL fail(char *error,size_t size,const char *message) { if(error && size) snprintf(error,size,"%s",message);return FALSE; }
static const unsigned char *take(Reader *r,size_t size) {
    if(!bounds(r->size,r->pos,size)) return NULL;
    const unsigned char *p=r->data+r->pos;r->pos+=size;return p;
}
static BOOL hash(BCRYPT_ALG_HANDLE alg,const unsigned char *bytes,size_t size,unsigned char digest[32]) {
    BCRYPT_HASH_HANDLE h=NULL;
    if(size>0xffffffffu || BCryptCreateHash(alg,&h,NULL,0,NULL,0,0)<0) return FALSE;
    BOOL ok=BCryptHashData(h,(PUCHAR)bytes,(ULONG)size,0)>=0 && BCryptFinishHash(h,digest,32,0)>=0;
    BCryptDestroyHash(h);return ok;
}
static const Section *section(const Image *image,uint32_t address,size_t size) {
    if(!size || !address || address>=image->image_size || size>image->image_size-address) return NULL;
    for(uint32_t i=0;i<image->section_count;i++) {
        const Section *s=image->sections+i;
        if(address>=s->rva && address-s->rva<s->size && size<=s->size-(address-s->rva)) return s;
    }
    return NULL;
}
static const unsigned char *read_rva(const Image *image,uint32_t address,size_t size) {
    const Section *s=section(image,address,size);
    if(!s || address-s->rva>s->raw_size || size>s->raw_size-(address-s->rva)) return NULL;
    size_t offset=(size_t)s->raw+address-s->rva;
    return bounds(image->size,offset,size)?image->data+offset:NULL;
}
static BOOL parse_image(const unsigned char *data,size_t size,Image *image) {
    memset(image,0,sizeof(*image));image->data=data;image->size=size;
    if(!bounds(size,0,64) || memcmp(data,"MZ",2)) return FALSE;
    uint32_t nt=u32(data+0x3c);
    if(!bounds(size,nt,24) || memcmp(data+nt,"PE\0\0",4) || u16(data+nt+4)!=0x8664) return FALSE;
    uint32_t count=u16(data+nt+6),optional_size=u16(data+nt+20);
    size_t opt=(size_t)nt+24,table=opt+optional_size;
    if(!count || count>MAX_SECTIONS || optional_size<144 || !bounds(size,opt,optional_size) ||
       !bounds(size,table,count*40) || u16(data+opt)!=0x20b || (u16(data+nt+22)&0x2000)) return FALSE;
    image->preferred_base=u64(data+opt+24);image->image_size=u32(data+opt+56);
    if(image->image_size<4096 || image->image_size>0x10000000 || image->preferred_base>UINT64_MAX-image->image_size ||
       u32(data+opt+108)<4) return FALSE;
    image->pdata=u32(data+opt+136);image->pdata_size=u32(data+opt+140);
    image->section_count=count;
    for(uint32_t i=0;i<count;i++) {
        const unsigned char *p=data+table+i*40;
        Section *s=image->sections+i;memcpy(s->name,p,8);
        uint32_t virtual_size=u32(p+8);s->rva=u32(p+12);s->raw_size=u32(p+16);s->raw=u32(p+20);
        s->size=virtual_size>s->raw_size?virtual_size:s->raw_size;s->flags=u32(p+36)&FLAGS;
        if(!s->rva || s->rva>=image->image_size || s->size>image->image_size-s->rva ||
           (s->raw_size && !bounds(size,s->raw,s->raw_size))) return FALSE;
        for(uint32_t j=0;j<i;j++) {
            const Section *other=image->sections+j;
            if(s->rva<other->rva+other->size && other->rva<s->rva+s->size) return FALSE;
            if(s->raw_size && other->raw_size && s->raw<other->raw+other->raw_size && other->raw<s->raw+s->raw_size) return FALSE;
        }
    }
    if(!image->pdata_size || image->pdata_size%12 || image->pdata_size>4*1024*1024) return FALSE;
    const unsigned char *pdata=read_rva(image,image->pdata,image->pdata_size);
    if(!pdata) return FALSE;
    uint32_t previous_end=0;
    for(uint32_t i=0;i<image->pdata_size;i+=12) {
        uint32_t start=u32(pdata+i),end=u32(pdata+i+4);
        const Section *s=end>start?section(image,start,end-start):NULL;
        if(!s || !(s->flags&EXECUTE) || start<previous_end) return FALSE;
        previous_end=end;
    }
    return TRUE;
}
static BOOL function_boundary(const Image *image,uint32_t start,uint32_t length,BOOL require_pdata) {
    const unsigned char *p=read_rva(image,image->pdata,image->pdata_size);
    if(!p) return FALSE;
    uint32_t left=0,right=image->pdata_size/12;
    while(left<right) {
        uint32_t mid=left+(right-left)/2,a=u32(p+mid*12),b=u32(p+mid*12+4);
        if(start<a) right=mid;
        else if(start>=b) left=mid+1;
        else return a==start && b-start==length;
    }
    return !require_pdata;
}
static BOOL masked(const Function *f,uint32_t offset) {
    for(uint32_t i=0;i<f->ref_count;i++) if(offset>=f->refs[i].offset && offset-f->refs[i].offset<f->refs[i].size) return TRUE;
    return FALSE;
}
static uint32_t ref_target(const Image *image,uint32_t start,const Reference *ref) {
    const unsigned char *p=read_rva(image,start+ref->offset,ref->size);
    if(!p) return 0;
    int64_t disp=ref->size==4?(int32_t)u32(p):(int8_t)*p;
    int64_t target=(int64_t)start+ref->end+disp;
    return target>0 && target<image->image_size?(uint32_t)target:0;
}
static BOOL match_functions(const Image *image,BCRYPT_ALG_HANDLE alg,Function *functions,uint32_t count,char *error,size_t error_size) {
    unsigned char *buffer=HeapAlloc(GetProcessHeap(),0,65536);
    if(!buffer) return fail(error,error_size,"compatibility memory allocation failed");
    BOOL ok=FALSE;
    for(uint32_t n=0;n<count;n++) {
        Function *f=functions+n;
        for(uint32_t s=0;s<image->section_count;s++) {
            const Section *sec=image->sections+s;
            if(!(sec->flags&EXECUTE) || sec->raw_size<f->length) continue;
            const unsigned char *bytes=image->data+sec->raw;
            uint32_t limit=sec->raw_size-f->length;
            for(uint32_t pos=0;pos<=limit;pos++) {
                BOOL anchor=TRUE;
                for(uint32_t i=0;i<f->anchor_size;i++) if(!masked(f,i) && bytes[pos+i]!=f->anchor[i]) {anchor=FALSE;break;}
                if(!anchor || !function_boundary(image,sec->rva+pos,f->length,f->pdata)) continue;
                memcpy(buffer,bytes+pos,f->length);
                for(uint32_t i=0;i<f->ref_count;i++) memset(buffer+f->refs[i].offset,0,f->refs[i].size);
                unsigned char digest[32];
                if(!hash(alg,buffer,f->length,digest)) goto done;
                if(memcmp(digest,f->hash,32)) continue;
                if(f->candidate_count==MAX_CANDIDATES) {fail(error,error_size,"too many matching function bodies");goto done;}
                f->candidates[f->candidate_count++]=sec->rva+pos;
            }
        }
        if(!f->candidate_count) {if(error && error_size) snprintf(error,error_size,"complete function %u did not match",n);goto done;}
        if(f->candidate_count==1) f->found=f->candidates[0];
        if(n<ZH_HOOK_COUNT && f->candidate_count!=1) {fail(error,error_size,"ambiguous text hook; first-hit matching refused");goto done;}
    }
    for(uint32_t pass=0;pass<count;pass++) {
        BOOL changed=FALSE;
        for(uint32_t n=0;n<count;n++) if(functions[n].found) {
            Function *f=functions+n;
            for(uint32_t r=0;r<f->ref_count;r++) {
                Reference *ref=f->refs+r;
                if(ref->role<0 || (uint32_t)ref->role>=count) continue;
                Function *callee=functions+ref->role;
                uint32_t target=ref_target(image,f->found,ref);BOOL candidate=FALSE;
                for(uint32_t c=0;c<callee->candidate_count;c++) if(callee->candidates[c]==target) candidate=TRUE;
                if(!candidate || (callee->found && callee->found!=target)) {fail(error,error_size,"call graph does not match");goto done;}
                if(!callee->found) {callee->found=target;changed=TRUE;}
            }
        }
        if(!changed) break;
    }
    for(uint32_t n=0;n<count;n++) {
        if(!functions[n].found) {fail(error,error_size,"ambiguous drawing helper");goto done;}
        for(uint32_t j=0;j<n;j++) if(functions[n].found<functions[j].found+functions[j].length && functions[j].found<functions[n].found+functions[n].length) {
            fail(error,error_size,"overlapping functions");goto done;
        }
    }
    ok=TRUE;
done:
    HeapFree(GetProcessHeap(),0,buffer);return ok;
}
static BOOL verify_references(const Image *image,BCRYPT_ALG_HANDLE alg,Function *functions,uint32_t count,uint32_t globals[4],char *error,size_t error_size) {
    Identity identities[1024];uint32_t used=0;
    for(uint32_t n=0;n<count;n++) {
        Function *f=functions+n;
        for(uint32_t r=0;r<f->ref_count;r++) {
            Reference *ref=f->refs+r;uint32_t target=ref_target(image,f->found,ref);
            const Section *s=section(image,target,1);
            if(!s || s->flags!=(ref->flags&FLAGS)) return fail(error,error_size,"reference section permissions changed");
            if(ref->role>=0 && (uint32_t)ref->role<count && target!=functions[ref->role].found) return fail(error,error_size,"function reference changed");
            if(ref->role>=(int32_t)count) {
                uint32_t g=(uint32_t)ref->role-count;
                if(g>=4 || (globals[g] && globals[g]!=target)) return fail(error,error_size,"global data references disagree");
                globals[g]=target;
                if(!(s->flags&0x80000000u) || !section(image,target,g==0 || g==2?8:4)) return fail(error,error_size,"invalid writable engine field");
            }
            if(ref->literal_length) {
                const unsigned char *literal=read_rva(image,target,ref->literal_length),*prefix=target>=16?read_rva(image,target-16,16):NULL;
                unsigned char digest[32];
                if(!literal || !prefix || u64(prefix)!=UINT64_MAX || u64(prefix+8)!=ref->literal_length ||
                   !hash(alg,literal,ref->literal_length,digest) || memcmp(digest,ref->literal_hash,32)) return fail(error,error_size,"referenced rendering literal changed");
            }
            BOOL exists=FALSE;
            for(uint32_t i=0;i<used;i++) {
                if(identities[i].old_target==ref->old_target) {
                    if(identities[i].new_target!=target) return fail(error,error_size,"shared reference identities changed");
                    exists=TRUE;
                } else if(identities[i].new_target==target) return fail(error,error_size,"distinct references collapsed");
            }
            if(!exists) {
                if(used==1024) return fail(error,error_size,"too many reference identities");
                identities[used++]=(Identity){ref->old_target,target};
            }
        }
    }
    for(uint32_t g=0;g<4;g++) if(!globals[g]) return fail(error,error_size,"required global field was not identified");
    return TRUE;
}
static BOOL context_digest(const Image *image,BCRYPT_ALG_HANDLE alg,uint32_t slot,uint32_t radius,unsigned char digest[32]) {
    if(slot<radius || !read_rva(image,slot-radius,radius*2)) return FALSE;
    unsigned char tokens[128*37];size_t length=0;
    for(uint32_t offset=0;offset<radius*2;offset+=8) {
        const unsigned char *raw=read_rva(image,slot-radius+offset,8);if(!raw) return FALSE;
        uint64_t value=u64(raw);
        if(value>=image->preferred_base && value-image->preferred_base<image->image_size) {
            uint32_t target=(uint32_t)(value-image->preferred_base);
            const Section *sec=section(image,target,1);
            const unsigned char *prefix=sec && target>=16?read_rva(image,target-16,16):NULL;
            uint64_t size=prefix?u64(prefix+8):0;
            const unsigned char *literal=prefix && u64(prefix)==UINT64_MAX && size>0 && size<=20000?read_rva(image,target,(size_t)size):NULL;
            if(literal) {
                tokens[length++]='S';uint32_t count=(uint32_t)size;memcpy(tokens+length,&count,4);length+=4;
                if(!hash(alg,literal,(size_t)size,tokens+length)) return FALSE;
                length+=32;
            } else {
                tokens[length++]='P';memcpy(tokens+length,sec?sec->name:(const unsigned char *)"headers",8);length+=8;
                uint32_t flags=sec?sec->flags:0;memcpy(tokens+length,&flags,4);length+=4;
            }
        } else {tokens[length++]='C';memcpy(tokens+length,raw,8);length+=8;}
    }
    return hash(alg,tokens,length,digest);
}
static BOOL find_scopes(const Image *image,BCRYPT_ALG_HANDLE alg,const Scope scopes[9],ZhCompatResult *result,char *error,size_t error_size) {
    for(uint32_t n=0;n<9;n++) {
        const Scope *scope=scopes+n;uint32_t found=0,found_slot=0,matches=0;
        for(uint32_t s=0;s<image->section_count;s++) {
            const Section *sec=image->sections+s;
            if(!(sec->flags&READABLE) || (sec->flags&EXECUTE) || sec->raw_size<scope->length+16) continue;
            const unsigned char *data=image->data+sec->raw;
            for(uint32_t pos=16;pos<=sec->raw_size-scope->length;pos++) {
                if(data[pos]!=scope->text[0] || u64(data+pos-16)!=UINT64_MAX || u64(data+pos-8)!=scope->length || memcmp(data+pos,scope->text,scope->length)) continue;
                uint32_t rva=sec->rva+pos;
                if(!scope->radius) {found=rva;matches++;continue;}
                uint64_t pointer=image->preferred_base+rva;
                for(uint32_t t=0;t<image->section_count;t++) {
                    const Section *table=image->sections+t;
                    if(!(table->flags&READABLE) || (table->flags&EXECUTE) || table->raw_size<8) continue;
                    for(uint32_t at=0;at<=table->raw_size-8;at+=8) {
                        if(u64(image->data+table->raw+at)!=pointer) continue;
                        uint32_t slot=table->rva+at;unsigned char digest[32];
                        if(context_digest(image,alg,slot,scope->radius,digest) && !memcmp(digest,scope->hash,32)) {
                            found=rva;found_slot=slot;matches++;
                        }
                    }
                }
            }
        }
        if(matches!=1) {if(error && error_size) snprintf(error,error_size,"scope %u had %u exact context matches",n,matches);return FALSE;}
        for(uint32_t j=0;j<n;j++) if(result->scopes[j].current_rva==found) return fail(error,error_size,"duplicate scoped text");
        result->scopes[n]=(ZhScopeRva){scope->legacy,found};result->scope_slots[n]=found_slot;
    }
    return TRUE;
}
BOOL zh_auto_detect(const unsigned char *file,size_t file_size,const unsigned char *metadata,size_t metadata_size,
                    ZhCompatResult *result,char *error,size_t error_size) {
    if(error && error_size) error[0]=0;
    if(!result || !file || !metadata || metadata_size<84 || metadata_size>2*1024*1024) return fail(error,error_size,"compatibility metadata missing or oversized");
    memset(result,0,sizeof(*result));Image image;
    if(!parse_image(file,file_size,&image)) return fail(error,error_size,"invalid x64 executable layout");
    BCRYPT_ALG_HANDLE alg=NULL;BOOL ok=FALSE;Function *functions=NULL;
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0)<0) return fail(error,error_size,"SHA256 unavailable");
    unsigned char digest[32];
    if(!hash(alg,metadata,metadata_size-32,digest) || memcmp(digest,metadata+metadata_size-32,32)) {fail(error,error_size,"compatibility checksum mismatch");goto done;}
    Reader reader={metadata,metadata_size-32,0};const unsigned char *head=take(&reader,52);
    if(!head || memcmp(head,"ZHCMP001",8) || u32(head+8)!=1) {fail(error,error_size,"unknown compatibility format");goto done;}
    uint32_t count=u32(head+12);
    if(count<16 || count>ZH_COMPAT_MAX_FUNCTIONS || u32(head+16)!=9) {fail(error,error_size,"invalid function or scope count");goto done;}
    char baseline_hash[65];for(uint32_t i=0;i<32;i++) sprintf(baseline_hash+i*2,"%02x",head[20+i]);
    const ZhGameVersion *baseline=zh_find_version(baseline_hash);
    if(!baseline || !baseline->layout.remap_scopes || baseline->layout.scope_count!=9) {fail(error,error_size,"unreviewed fingerprint baseline");goto done;}
    const uint32_t baseline_helpers[]={baseline->layout.begin,baseline->layout.end,baseline->layout.uv,baseline->layout.vertex,baseline->layout.color};
    const uint32_t baseline_globals[]={baseline->layout.font_slot,baseline->layout.batch_count,baseline->layout.gui_slot,baseline->layout.current_color};
    functions=HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(Function)*count);
    if(!functions) goto done;
    for(uint32_t n=0;n<count;n++) {
        const unsigned char *p=take(&reader,80);if(!p) {fail(error,error_size,"truncated function metadata");goto done;}
        Function *f=functions+n;
        f->old_rva=u32(p);f->length=u32(p+4);f->pdata=u32(p+8);f->copy_size=u32(p+12);f->anchor_size=u32(p+16);f->ref_count=u32(p+20);
        f->hash=p+24;f->anchor=p+56;
        if(!f->length || f->length>65536 || f->copy_size>f->length || f->pdata>1 || f->anchor_size!=(f->length<24?f->length:24) || f->ref_count>MAX_REFS ||
           (n<11 && (f->old_rva!=baseline->hooks[n].rva || f->copy_size!=baseline->hooks[n].size || memcmp(f->anchor,baseline->hooks[n].signature,f->copy_size))) ||
           (n>=11 && f->copy_size) || (n>=11 && n<16 && f->old_rva!=baseline_helpers[n-11])) {fail(error,error_size,"invalid function constraints");goto done;}
        for(uint32_t j=0;j<n;j++) if(functions[j].old_rva==f->old_rva) {fail(error,error_size,"duplicate baseline function role");goto done;}
        if(f->ref_count) {
            f->refs=HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(Reference)*f->ref_count);
            if(!f->refs) goto done;
        }
        for(uint32_t r=0;r<f->ref_count;r++) {
            p=take(&reader,60);if(!p) {fail(error,error_size,"truncated reference metadata");goto done;}
            Reference *ref=f->refs+r;
            ref->offset=u32(p);ref->size=u32(p+4);ref->end=u32(p+8);ref->role=(int32_t)u32(p+12);
            ref->old_target=u32(p+16);ref->flags=u32(p+20);ref->literal_length=u32(p+24);ref->literal_hash=p+28;
            if((ref->size!=1 && ref->size!=4) || ref->size>f->length || ref->offset>f->length-ref->size ||
               ref->end<ref->offset+ref->size || ref->end>f->length || ref->role< -1 || ref->role>=(int32_t)count+4 ||
               !ref->old_target || (ref->flags&~FLAGS) || ref->literal_length>20000 ||
               (n<11 && ref->offset<f->copy_size)) {fail(error,error_size,"invalid relocation constraints");goto done;}
            for(uint32_t j=0;j<r;j++) if(ref->offset<f->refs[j].offset+f->refs[j].size && f->refs[j].offset<ref->offset+ref->size) {fail(error,error_size,"overlapping relocation fields");goto done;}
        }
    }
    for(uint32_t n=0;n<count;n++) for(uint32_t r=0;r<functions[n].ref_count;r++) {
        Reference *ref=functions[n].refs+r;
        if(ref->role>=0) {
            uint32_t expected=(uint32_t)ref->role<count?functions[ref->role].old_rva:baseline_globals[(uint32_t)ref->role-count];
            if(ref->old_target!=expected) {fail(error,error_size,"baseline reference role mismatch");goto done;}
        } else {
            for(uint32_t j=0;j<count;j++) if(ref->old_target==functions[j].old_rva) {fail(error,error_size,"required call relation omitted");goto done;}
            for(uint32_t j=0;j<4;j++) if(ref->old_target==baseline_globals[j]) {fail(error,error_size,"required global relation omitted");goto done;}
        }
    }
    if(!hash(alg,metadata,reader.pos,digest)) goto done;
#ifdef ZH_COMPAT_TEST_CONTRACT
    char contract_hex[65];for(uint32_t i=0;i<32;i++) sprintf(contract_hex+i*2,"%02x",digest[i]);
    if(strcmp(contract_hex,ZH_COMPAT_TEST_CONTRACT)) {fail(error,error_size,"test code contract differs");goto done;}
#else
    if(memcmp(digest,zh_compat_contract_digest,32)) {fail(error,error_size,"code contract differs; runtime rebuild required");goto done;}
#endif
    Scope scopes[9];
    for(uint32_t n=0;n<9;n++) {
        const unsigned char *p=take(&reader,44);if(!p) {fail(error,error_size,"truncated scope metadata");goto done;}
        Scope *s=scopes+n;s->legacy=u32(p);s->length=u32(p+4);s->radius=u32(p+8);s->hash=p+12;
        if(s->legacy!=baseline->layout.scopes[n].legacy_rva || !s->length || s->length>20000 || (s->radius!=0 && s->radius!=128 && s->radius!=512)) {fail(error,error_size,"invalid scope constraints");goto done;}
        s->text=take(&reader,s->length);if(!s->text) {fail(error,error_size,"truncated scoped text");goto done;}
        if(s->legacy!=zh_compat_scope_contracts[n].legacy || s->length!=zh_compat_scope_contracts[n].length ||
           !hash(alg,s->text,s->length,digest) || memcmp(digest,zh_compat_scope_contracts[n].hash,32)) {fail(error,error_size,"scoped source contract changed");goto done;}
    }
    if(reader.pos!=reader.size) {fail(error,error_size,"trailing compatibility data");goto done;}
    if(!match_functions(&image,alg,functions,count,error,error_size)) goto done;
    uint32_t globals[4]={0};
    if(!verify_references(&image,alg,functions,count,globals,error,error_size) || !find_scopes(&image,alg,scopes,result,error,error_size)) goto done;
    result->version.id="auto-compatible-steam";result->version.exe_sha256="structurally-verified";
    result->version.layout=(ZhEngineLayout){.font_slot=globals[0],.begin=functions[11].found,.end=functions[12].found,
        .uv=functions[13].found,.vertex=functions[14].found,.color=functions[15].found,
        .batch_count=globals[1],.gui_slot=globals[2],.current_color=globals[3],
        .scopes=result->scopes,.scope_count=9,.remap_scopes=TRUE};
    result->function_count=count;
    for(uint32_t n=0;n<count;n++) {result->function_rvas[n]=functions[n].found;result->function_sizes[n]=functions[n].length;}
    for(uint32_t n=0;n<11;n++) {
        ZhHookSite *hook=result->version.hooks+n;hook->rva=functions[n].found;hook->size=functions[n].copy_size;
        memcpy(hook->signature,read_rva(&image,hook->rva,hook->size),hook->size);
    }
    ok=TRUE;
done:
    if(functions) {
        uint32_t allocated=u32(metadata+12);
        if(allocated<=ZH_COMPAT_MAX_FUNCTIONS) for(uint32_t n=0;n<allocated;n++) if(functions[n].refs) HeapFree(GetProcessHeap(),0,functions[n].refs);
        HeapFree(GetProcessHeap(),0,functions);
    }
    if(alg) BCryptCloseAlgorithmProvider(alg,0);
    if(!ok && error && error_size && !error[0]) fail(error,error_size,"compatibility validation failed");
    return ok;
}
BOOL zh_read_file(const wchar_t *path,size_t limit,unsigned char **bytes,size_t *size) {
    *bytes=NULL;*size=0;
    HANDLE f=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(f==INVALID_HANDLE_VALUE) return FALSE;
    LARGE_INTEGER length;BOOL ok=FALSE;DWORD got;
    if(!GetFileSizeEx(f,&length) || length.QuadPart<=0 || (uint64_t)length.QuadPart>limit || length.QuadPart>0xffffffffu) goto done;
    unsigned char *buffer=HeapAlloc(GetProcessHeap(),0,(size_t)length.QuadPart);if(!buffer) goto done;
    if(ReadFile(f,buffer,(DWORD)length.QuadPart,&got,NULL) && got==(DWORD)length.QuadPart) {*bytes=buffer;*size=got;ok=TRUE;}
    else HeapFree(GetProcessHeap(),0,buffer);
done:CloseHandle(f);return ok;
}
static BOOL readable_memory(const unsigned char *p,size_t size) {
    uintptr_t at=(uintptr_t)p;
    if(size>UINTPTR_MAX-at) return FALSE;
    uintptr_t end=at+size;
    while(at<end) {
        MEMORY_BASIC_INFORMATION info;
        if(!VirtualQuery((const void *)at,&info,sizeof(info)) || info.State!=MEM_COMMIT || (info.Protect&(PAGE_GUARD|PAGE_NOACCESS)) ||
           !(info.Protect&(PAGE_READONLY|PAGE_READWRITE|PAGE_WRITECOPY|PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY))) return FALSE;
        uintptr_t next=(uintptr_t)info.BaseAddress+info.RegionSize;
        if(next<=at) return FALSE;
        at=next;
    }
    return TRUE;
}
BOOL zh_auto_verify_loaded(const unsigned char *file,size_t file_size,const unsigned char *base,
                           const ZhCompatResult *result,char *error,size_t error_size) {
    Image image;if(!base || !parse_image(file,file_size,&image)) return fail(error,error_size,"loaded executable identity unavailable");
    for(uint32_t n=0;n<result->function_count;n++) {
        uint32_t rva=result->function_rvas[n],size=result->function_sizes[n];
        const unsigned char *raw=read_rva(&image,rva,size);
        if(!raw || !readable_memory(base+rva,size) || memcmp(base+rva,raw,size)) return fail(error,error_size,"loaded function differs from verified file");
    }
    for(uint32_t n=0;n<9;n++) {
        uint32_t rva=result->scopes[n].current_rva;const unsigned char *prefix=rva>=16?read_rva(&image,rva-16,16):NULL;
        uint64_t length=prefix?u64(prefix+8):0;
        const unsigned char *raw=length && length<=20000?read_rva(&image,rva,(size_t)length):NULL;
        if(!raw || !readable_memory(base+rva-16,(size_t)length+16) || memcmp(base+rva-16,prefix,16) || memcmp(base+rva,raw,(size_t)length)) return fail(error,error_size,"loaded scoped text changed");
        uint32_t slot=result->scope_slots[n];
        if(slot && (!readable_memory(base+slot,8) || u64(base+slot)!=(uintptr_t)(base+rva))) return fail(error,error_size,"loaded scope reference changed");
    }
    return TRUE;
}
