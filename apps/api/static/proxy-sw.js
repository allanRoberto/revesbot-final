self.addEventListener("fetch", function (event) {
  const request = event.request;
  const url = new URL(request.url);

  // Requisições locais (ou seja, ao seu próprio servidor)
  const isLocal = url.origin === self.location.origin;

  // Intercepta qualquer requisição local que não seja do próprio /proxy
  if (
    isLocal &&
    !url.pathname.startsWith("/proxy") &&
    url.pathname !== "/static/proxy-sw.js"
  ) {
    const proxiedUrl = `/proxy?url=https://lotogreen.bet.br${url.pathname}`;
    console.log("🔁 Proxy SW redirecionando:", url.pathname, "→", proxiedUrl);
    event.respondWith(fetch(proxiedUrl));
  }
});
