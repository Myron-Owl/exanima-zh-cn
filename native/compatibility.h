#ifndef EXANIMA_ZH_COMPATIBILITY_H
#define EXANIMA_ZH_COMPATIBILITY_H
#include "version_profiles.h"
#define ZH_COMPAT_MAX_FUNCTIONS 32
typedef struct {
    ZhGameVersion version;
    ZhScopeRva scopes[9];
    uint32_t function_count, function_rvas[ZH_COMPAT_MAX_FUNCTIONS], function_sizes[ZH_COMPAT_MAX_FUNCTIONS];
    uint32_t scope_slots[9];
} ZhCompatResult;
BOOL zh_read_file(const wchar_t *path,size_t limit,unsigned char **bytes,size_t *size);
BOOL zh_auto_detect(const unsigned char *file,size_t file_size,const unsigned char *metadata,size_t metadata_size,
                    ZhCompatResult *result,char *error,size_t error_size);
BOOL zh_auto_verify_loaded(const unsigned char *file,size_t file_size,const unsigned char *base,
                           const ZhCompatResult *result,char *error,size_t error_size);
#endif
