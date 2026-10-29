#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
static void show(const char *label, const char *host, int port){
  ADDRINFOA hints; ADDRINFOA *res=NULL; char ip[64]="?";
  memset(&hints,0,sizeof(hints)); hints.ai_family=AF_INET; hints.ai_socktype=SOCK_STREAM;
  int r=getaddrinfo(host, "443", &hints, &res);
  if(r==0 && res){
    struct sockaddr_in *sa=(struct sockaddr_in*)res->ai_addr;
    sprintf(ip,"%u.%u.%u.%u", (sa->sin_addr.s_addr)&0xff,(sa->sin_addr.s_addr>>8)&0xff,(sa->sin_addr.s_addr>>16)&0xff,(sa->sin_addr.s_addr>>24)&0xff);
  }
  printf("%-32s getaddrinfo rc=%d ip=%s\n", label, r, ip);
  if(res) freeaddrinfo(res);
}
int main(void){
  WSADATA wd; WSAStartup(0x202,&wd);
  SetEnvironmentVariableA("SPOOF_NET_CFG","C:\\SHARE\\hwid\\_dns_probe.cfg");
  HMODULE h=LoadLibraryA("C:\\SHARE\\hwid\\rfspoof.net.dll");
  printf("dll=%p\n",(void*)h); if(!h) return 1;
  Sleep(700);
  WCHAR real[64]; DWORD n=64; GetComputerNameW(real,&n);
  char realA[64]; WideCharToMultiByte(CP_ACP,0,real,-1,realA,sizeof(realA),0,0);
  printf("real hostname=%s\n", realA);
  show("real hostname", realA, 443);
  show("fake hostname", "DESKTOP-0B3C924", 443);
  show("cerberus-games.com", "cerberus-games.com", 443);
  struct hostent *he=gethostbyname(realA);
  if(he && he->h_addr_list[0]) printf("gethostbyname(real) -> %u.%u.%u.%u\n", (unsigned char)he->h_addr_list[0][0],(unsigned char)he->h_addr_list[0][1],(unsigned char)he->h_addr_list[0][2],(unsigned char)he->h_addr_list[0][3]);
  return 0;
}
