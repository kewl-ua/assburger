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
  ADDRINFOW hintsW; ADDRINFOW *resW=NULL;
  memset(&hintsW,0,sizeof(hintsW)); hintsW.ai_family=AF_INET; hintsW.ai_socktype=SOCK_STREAM;
  int r=GetAddrInfoW(L"cerberus-games.com", L"443", &hintsW, &resW);
  printf("GetAddrInfoW rc=%d res=%p\n", r, (void*)resW); fflush(stdout);
  if(resW){ struct sockaddr_in *sa=(struct sockaddr_in*)resW->ai_addr; printf("w ip=%08X port=%u\n", sa->sin_addr.s_addr, ntohs(sa->sin_port)); fflush(stdout); FreeAddrInfoW(resW); printf("w freed\n"); fflush(stdout); }
  struct hostent *he=gethostbyname("cerberus-games.com");
  printf("ghbn real=%p\n",(void*)he); fflush(stdout);
  if(he && he->h_addr_list[0]) printf("ghbn ip=%u.%u.%u.%u\n",(unsigned char)he->h_addr_list[0][0],(unsigned char)he->h_addr_list[0][1],(unsigned char)he->h_addr_list[0][2],(unsigned char)he->h_addr_list[0][3]);
  fflush(stdout);
  return 0;
}
