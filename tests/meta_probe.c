#include <windows.h>
#include <stdio.h>
int main(int argc, char **argv){
  const char *cfg = argc>1?argv[1]:"C:\\SHARE\\hwid\\spoof_1.cfg";
  const char *dll = argc>2?argv[2]:"C:\\SHARE\\hwid\\rfspoof.new.dll";
  SetEnvironmentVariableA("SPOOF_CFG", cfg);
  HMODULE h = LoadLibraryA(dll);
  printf("dll=%p\n", (void*)h);
  if(!h) return 1;
  Sleep(700);
  BOOL d = CreateDirectoryW(L"C:\\ProgramData\\Microsoft\\DeviceSync\\profiletest", NULL);
  printf("CreateDirectory -> %d err=%lu\n", d, GetLastError());
  HANDLE f = CreateFileW(L"C:\\ProgramData\\Microsoft\\DeviceSync\\profiletest\\marker.txt",
                         GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  printf("CreateFile -> %p err=%lu\n", f, GetLastError());
  if(f!=INVALID_HANDLE_VALUE){ DWORD w; WriteFile(f,"meta-ok",7,&w,NULL); CloseHandle(f); }
  printf("GetFileAttributes(DeviceSync path) -> 0x%lX err=%lu\n",
         GetFileAttributesW(L"C:\\ProgramData\\Microsoft\\DeviceSync\\profiletest\\marker.txt"), GetLastError());
  return 0;
}
