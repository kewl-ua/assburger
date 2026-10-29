#include <windows.h>
#include <stdio.h>
int main(int argc, char **argv){
  if(argc>1){ SetEnvironmentVariableA("SPOOF_CFG", argc>2?argv[2]:"C:\\SHARE\\hwid\\spoof_1.cfg"); HMODULE h=LoadLibraryA(argv[1]); printf("dll=%p\n",(void*)h); Sleep(500); }
  DISPLAY_DEVICEW a; int i;
  for(i=0;;i++){ a.cb=sizeof(a); if(!EnumDisplayDevicesW(NULL,i,&a,0)) break;
    printf("adapter[%d] name=%S id=%S\n",i,a.DeviceName,a.DeviceID);
    DISPLAY_DEVICEW m; int j;
    for(j=0;;j++){ m.cb=sizeof(m); if(!EnumDisplayDevicesW(a.DeviceName,j,&m,0)) break;
      printf("  monitor[%d] name=%S id=%S\n",j,m.DeviceName,m.DeviceID); }
  }
  return 0;
}
