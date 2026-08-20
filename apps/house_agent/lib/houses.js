// Casas atendidas pelo modo navegador (plataforma Nuxt/BFF + Cloudflare).
// A LotoGreen NÃO entra aqui (usa o proxy HTTP do auth_api).
const HOUSE_DOMAINS = {
  esportiva: 'esportiva.bet.br',
  bateu: 'bateu.bet.br',
};

function domainFor(house) {
  return HOUSE_DOMAINS[house] || null;
}

module.exports = { HOUSE_DOMAINS, domainFor };
