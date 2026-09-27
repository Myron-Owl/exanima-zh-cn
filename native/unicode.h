#ifndef EXANIMA_ZH_UNICODE_H
#define EXANIMA_ZH_UNICODE_H
#include <windows.h>
typedef void (*ZhLogger)(const char*,...);
BOOL zh_load(HMODULE module, unsigned char *image, ZhLogger logger);
int zh_width(const char *source, void *font);
BOOL zh_draw(const char *source, float x, float y, BOOL batched, float *right);
BOOL zh_draw_clipped(const char *source,float x,float y,float width,BOOL centered,float *right);
BOOL zh_measure_text(void *renderer,const char *source,int x,int y);
BOOL zh_draw_text(void *renderer,const char *source,int x,int y,int skip,const void *selection);
BOOL zh_has_translation(const char *source);
int zh_draw_block(const char *source,int length,float x,float y,int width,int height,int skip,BOOL centered);
int zh_block_lines(const char *source,int length,int width,void *font);
#endif
