#define WIN32_LEAN_AND_MEAN
#include "unicode.h"
#include <stdio.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#ifdef ZH_VERIFY
int zh_test_translate(const char *source,int length,char *out,int capacity);
static int translations(const char *path) {
    FILE *file=fopen(path,"rb");if(!file) return 60;
    uint32_t count,layouts=0;if(fread(&count,4,1,file)!=1) return 61;
    for(uint32_t i=0;i<count;i++) {
        uint32_t sizes[2];if(fread(sizes,4,2,file)!=2 || sizes[0]>100000 || sizes[1]>100000) return 62;
        struct {int64_t refcount,length;char data[100001];} text={-1,(int64_t)sizes[0],{0}};
        char *source=text.data;char expected[100001],actual[100001];
        if(fread(source,1,sizes[0],file)!=sizes[0] || fread(expected,1,sizes[1],file)!=sizes[1]) return 63;
        source[sizes[0]]=0;expected[sizes[1]]=0;
        int n=zh_test_translate(source,(int)sizes[0],actual,sizeof(actual)-1);
        if((!sizes[1] && n!=-1) || (sizes[1] && (n!=(int)sizes[1] || memcmp(actual,expected,sizes[1])))) {
            if(n>=0) actual[n]=0;
            printf("TRANSLATION_FAIL %u source=%s expected=%s actual=%s result=%d\n",i,source,expected,n>=0?actual:"<unmatched>",n);
            fclose(file);return 64;
        }
        // Raw engine variable templates are data, not display text. Their
        // expanded player-name variants are separate measured fixtures.
        if(sizes[1] && source[0]!='@' && !strstr(source,"{Actor[")) {
            int font[8]={0};font[4]=30;font[7]=36;
            struct {void *vmt;int x,y,width,height,reserved,left,align,padding;void *font;int leading;unsigned char format,pad[3];float italic;} r={0};
            r.font=font;r.height=100000;r.format=1;
            for(int width=320;width<=960;width+=320) {
                r.width=width;r.x=123;r.y=456;
                if(!zh_measure_text(&r,source,0,0) || r.y<=0) {printf("MEASURE_FAIL %u width=%d source=%s\n",i,width,source);return 65;}
                layouts++;
            }
        }
    }
    fclose(file);printf("EXACT_OUTPUT_CASES_PASSED=%u; LAYOUT_CHECKS_PASSED=%u (320/640/960)\n",count,layouts);return 0;
}
#endif
static void report(const char *format,...) {va_list args;va_start(args,format);vprintf(format,args);puts("");va_end(args);}
static int paragraphs(unsigned char *fake_image) {
    struct {int64_t refcount,length;char data[256];} text={-1,0,{0}};
    int font[8]={0};font[4]=32;font[7]=36;
    struct {void *vmt;int x,y,width,height,reserved,left,align,padding;void *font;int leading;unsigned char format,pad[3];float italic;} r={0};
    r.font=font;r.width=64;r.height=500;r.format=1;
    const char *keys[]={"zh.test.wrap","zh.test.crlf","zh.test.emptyline","zh.test.color","zh.test.alpha","zh.test.unknown","zh.test.literal\\path\r\n"};
    int heights[]={72,108,108,72,36,-1,36};
    for(size_t i=0;i<sizeof(keys)/sizeof(keys[0]);i++) {
        strcpy(text.data,keys[i]);text.length=strlen(text.data);r.x=123;r.y=456;
        BOOL got=zh_measure_text(&r,text.data,10,20);
        if(heights[i]<0) {if(got || r.x!=123 || r.y!=456) return 20+(int)i;}
        else if(!got || r.x!=10 || r.y!=20+heights[i]) {printf("LAYOUT_FAIL %s %d %d\n",keys[i],got,r.y);return 20+(int)i;}
    }
    r.font=NULL;if(zh_measure_text(&r,text.data,0,0)) return 29;
    r.font=font;r.width=0;if(zh_measure_text(&r,text.data,0,0)) return 30;
    if(zh_block_lines("zh.test.wrap",12,64,font)!=2) return 31;
    if(zh_block_lines("zh.test.wrap",12,32,font)!=4) return 32;
    if(zh_block_lines("zh.test.wrap",11,64,font)!=-1) return 33;
    if(zh_block_lines("zh.test.crlf",12,64,font)!=2) return 34;
    if(zh_block_lines("zh.test.color",13,64,font)!=-1) return 35;
    struct {int64_t refcount,length;char data[32];} scoped={-1,14,"zh.test.scoped"};
    int global_width=zh_width(scoped.data,font);
    memcpy(fake_image+0x123450-8,&scoped.length,8);memcpy(fake_image+0x123450,scoped.data,15);
    int scoped_width=zh_width((const char*)fake_image+0x123450,font);
    if(scoped_width<=0 || global_width<=scoped_width) return 39;
    struct {int64_t refcount,length;char data[256];} manual={-1,0,
        "\r\n[algn=2][tcol=FFE399]MOVEMENT[/tcol]\r\n[algn=0]\r\n[rimg=TutMvmnt01]\r\n\r\nDynamic Shift binding."};
    manual.length=strlen(manual.data);r.width=700;r.height=1000;r.x=123;r.y=456;
    // A known heading with unrelated body must never borrow a chapter or
    // silently replace the player's actual binding with a default key.
    if(zh_has_translation(manual.data)) return 36;
    if(zh_measure_text(&r,manual.data,0,0)) return 37;
    struct {int64_t refcount,length;char data[64];} category={-1,5,"Force"};
    if(!zh_has_translation(category.data)) return 43;
    struct {int64_t refcount,length;char data[128];} item={-1,0,"A well made elegant shirt in good condition."};
    item.length=strlen(item.data);
    if(!zh_has_translation(item.data) || zh_width(item.data,font)<=0) return 44;
    puts("MANUAL_UNRELATED_BODY_REFUSED; FULL_EXPANDED_CHAPTERS_TESTED_BY_VERIFY_TRANSLATIONS");
    puts("SCOPED_TRANSLATION_PRECEDENCE_CHECK_PASSED");
    puts("DYNAMIC_POWER_CATEGORY_AND_ITEM_DESCRIPTION_CHECKS_PASSED");
    puts("PARAGRAPH_WRAP_CRLF_COLOR_ESCAPE_FALLBACK_CHECKS_PASSED");return 0;
}
int main(int argc,char **argv) {
    (void)argv;
    unsigned char *fake_image=VirtualAlloc(NULL,0x600000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!fake_image) return 40;
    if(!zh_load(GetModuleHandleW(NULL),fake_image,report)) {puts("ASSET_LOAD_REFUSED");return 2;}
#ifdef ZH_VERIFY
    if(argc==3 && !strcmp(argv[1],"--translations")) return translations(argv[2]);
#endif
    struct {int64_t refcount,length;char data[32];} label={-1,14,"Audio volume: "};
    int font[8]={0};font[4]=30;
    int width=zh_width(label.data,font);
    if(width<=0 || width>=150) return 3;
    printf("AUDIO_WIDTH_30=%d\n",width);
    font[4]=60;
    int doubled=zh_width(label.data,font);
    if(doubled<2*width-1 || doubled>2*width+1) return 4;
    label.length=4;strcpy(label.data,"Test");
    if(zh_width(label.data,font)!=-1 || zh_width(NULL,font)!=-1) return 5;
    if(argc>1) {
        int64_t back_length=4;memcpy(fake_image+0x305150-8,&back_length,8);memcpy(fake_image+0x305150,"Back",5);
        if(zh_width((const char*)fake_image+0x305150,font)<=0) return 41;
        label.length=4;strcpy(label.data,"Back");if(zh_width(label.data,font)!=-1) return 42;
        puts("SCOPED_BACK_DOES_NOT_REPLACE_FILE_BROWSER_BACK");
    }
    puts("UNICODE_ASSET_AND_MEASUREMENT_CHECKS_PASSED");return argc>1?paragraphs(fake_image):0;
}
