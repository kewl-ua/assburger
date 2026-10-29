#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
int main(void){
  WSADATA wd; WSAStartup(0x202,&wd);
  SetEnvironmentVariableA("SPOOF_NET_CFG","C:\\SHARE\\hwid\\_dns_probe.cfg");
  HMODULE h=LoadLibraryA("C:\\SHARE\\hwid\\rfspoof.net.dll");
  printf("dll=%p\n",(void*)h); fflush(stdout);
  Sleep(700);
  WCHAR real[64]; DWORD n=64; GetComputerNameW(real,&n);
  char realA[64]; WideCharToMultiByte(CP_ACP,0,real,-1,realA,sizeof(realA),0,0);
  printf("real=%s\n", realA); fflush(stdout);
  ADDRINFOA hints; ADDRINFOA *res=NULL;
  memset(&hints,0,sizeof(hints)); hints.ai_family=AF_INET; hints.ai_socktype=SOCK_STREAM;
  int r=getaddrinfo(realA,"443",&hints,&res);
  printf("own rc=%d res=%p\n", r, (void*)res); fflush(stdout);
  if(res){ struct sockaddr_in *sa=(struct sockaddr_in*)res->ai_addr; printf("ip=%08X port=%u\n", sa->sin_addr.s_addr, ntohs(sa->sin_port)); fflush(stdout); freeaddrinfo(res); printf("freed\n"); fflush(stdout); }
  struct hostent *he=gethostbyname(realA);
  printf("ghbn=%p\n", (void*)he); fflush(stdout);
  return 0;
}
