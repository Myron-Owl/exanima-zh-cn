// Exercise the actual Unicode draw paths against the verified engine batch contract.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
static GLint bound_texture=77,active_unit=0x84c0;
static HGLRC WINAPI test_context(void) {return (HGLRC)(uintptr_t)1;}
static void APIENTRY test_get(GLenum key,GLint *out) {*out=key==0x84e0?active_unit:bound_texture;}
static void APIENTRY test_bind(GLenum target,GLuint texture) {(void)target;bound_texture=(GLint)texture;}
static void APIENTRY test_active(GLenum unit) {active_unit=(GLint)unit;}
#define wglGetCurrentContext test_context
#define glGetIntegerv test_get
#define glBindTexture test_bind
#include "unicode.c"
static int ends,stale_draws,vertices;
static void report(const char *format,...) {(void)format;}
static void mock_begin(void) {*(int*)(image_base+0x58ac20)=0;}
static void mock_end(void) {
    ends++;
    if(bound_texture==77 && *(int*)(image_base+0x58ac20)>0) stale_draws++;
    // Verified engine End submits without clearing the vertex count.
}
static void mock_uv(float u,float v) {(void)u;(void)v;}
static void mock_vertex(float x,float y) {(void)x;(void)y;vertices++;(*(int*)(image_base+0x58ac20))++;}
static void mock_color(void *rgba) {memcpy(image_base+0x5aad00,rgba,4);}
static void thunk(unsigned char *at,void *fn) {
    unsigned char code[14]={0xff,0x25,0,0,0,0};memcpy(code+6,&fn,8);memcpy(at,code,sizeof(code));
}
static void reset_stale(void) {ends=stale_draws=vertices=0;bound_texture=77;*(int*)(image_base+0x58ac20)=8;}
int main(void) {
    unsigned char *memory=VirtualAlloc(NULL,0x600000,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    if(!memory || !zh_load(GetModuleHandleW(NULL),memory,report)) return 2;
    thunk(memory+0x1f6c00,mock_begin);thunk(memory+0x1f6f10,mock_end);
    thunk(memory+0x1f6de0,mock_uv);thunk(memory+0x1f6ca0,mock_vertex);thunk(memory+0x1f6e60,mock_color);
    FlushInstructionCache(GetCurrentProcess(),memory,0x600000);
    int font[8]={0};font[3]=36;font[4]=30;font[7]=36;
    *(void**)(memory+0x496650)=font;*(void**)(memory+0x5ae0d0)=memory+0x590000;
    memset(memory+0x5900e4,255,4);memset(memory+0x5aad00,255,4);
    texture_context=(HGLRC)(uintptr_t)1;active_texture=test_active;textures[0]=99;
    struct {int64_t refs,length;char source[32];} text={-1,14,"Audio volume: "};
    TextRenderer r={.font=font,.width=700,.height=300,.format=1};
    reset_stale();
    if(!zh_draw_text(&r,text.source,8,0,0,NULL)) return 3;
    printf("RICH_PARAGRAPH stale=%d submits=%d vertices=%d\n",stale_draws,ends,vertices);
    if(stale_draws || ends!=1 || vertices<=0 || bound_texture!=77) return 10;
    reset_stale();
    if(zh_draw_block(text.source,14,8,0,700,300,0,FALSE)<0) return 4;
    printf("RAW_PARAGRAPH stale=%d submits=%d vertices=%d\n",stale_draws,ends,vertices);
    if(stale_draws || ends!=1 || vertices<=0 || bound_texture!=77) return 11;
    reset_stale();float right;
    if(!zh_draw(text.source,8,36,TRUE,&right)) return 5;
    printf("BATCH_LABEL pending_submits=%d total_submits=%d remaining_vertices=%d\n",stale_draws,ends,*(int*)(memory+0x58ac20));
    if(stale_draws!=1 || ends!=2 || *(int*)(memory+0x58ac20)!=0 || bound_texture!=77) return 12;
    puts("RENDER_BATCH_OWNERSHIP_CHECKS_PASSED");return 0;
}
