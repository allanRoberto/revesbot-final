// Conversão número da roleta -> betCode da Pragmatic e montagem do <lpbet>.
// Regra (portada de apps/bot_automatico/bot_aposta.js):
//   betCode = (n === 0) ? 2 : n + 3
// Cada aposta é um <bet amt bc ck/>, agrupados num <lpbet> dentro de <command>.

function betCodeForNumber(n) {
  const num = Number(n);
  if (!Number.isInteger(num) || num < 0 || num > 36) {
    throw new Error(`Número de aposta inválido: ${n}`);
  }
  return num === 0 ? 2 : num + 3;
}

// Monta a mensagem XML de aposta para a mesa.
// gameInfo: { game, table } extraído do <betsOpen ...>.
// bets: { numero: valor } — cada número com o SEU valor acumulado (o comando
// lpbet substitui o slip inteiro, então enviamos o estado completo).
function buildBetMessage(gameInfo, bets) {
  if (!gameInfo || !gameInfo.game || !gameInfo.table) {
    throw new Error('Informações da mesa (game/table) desconhecidas.');
  }
  const entries = Object.entries(bets || {});
  if (entries.length === 0) {
    throw new Error('Lista de apostas vazia.');
  }

  const ck = Date.now().toString();
  const betsXML = entries
    .map(([n, value]) => {
      const amt = Number(value);
      if (!Number.isFinite(amt) || amt <= 0) {
        throw new Error(`Valor de aposta inválido para o número ${n}: ${value}`);
      }
      return `<bet amt="${amt}" bc="${betCodeForNumber(n)}" ck="${ck}" />`;
    })
    .join('');

  return (
    `<command channel="table-${gameInfo.table}" >` +
    `<lpbet gm="roulette_desktop" gId="${gameInfo.game}" ck="${ck}">` +
    betsXML +
    `</lpbet></command>`
  );
}

module.exports = { betCodeForNumber, buildBetMessage };
