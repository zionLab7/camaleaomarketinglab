"""Bounded HTTPS reference downloads. Public DNS only; no redirects or proxies."""
import http.client,ipaddress,socket,ssl
from urllib.parse import urlsplit
from brand import public_https

def read_public(url,limit=2_000_000):
 public_https(url);p=urlsplit(url)
 addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
 if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):raise ValueError('Fonte resolveu para endereço não público')
 # Pin the checked address while preserving the hostname for SNI/certificate checks.
 class Pinned(http.client.HTTPSConnection):
  def connect(self):
   self.sock=socket.create_connection((addresses[0][4][0],443),timeout=20)
   self.sock=ssl.create_default_context().wrap_socket(self.sock,server_hostname=p.hostname)
 c=Pinned(p.hostname,timeout=20)
 try:
  c.request('GET',p.path+('?' +p.query if p.query else '') or '/',headers={'User-Agent':'CamaleaoMarketingLab/1.0 (+editorial reference)'})
  response=c.getresponse()
  if response.status!=200:raise ValueError('Fonte exige redirecionamento ou retornou HTTP '+str(response.status))
  raw=response.read(limit+1)
  if len(raw)>limit:raise ValueError('Fonte excede limite de leitura')
  return raw
 finally:c.close()
