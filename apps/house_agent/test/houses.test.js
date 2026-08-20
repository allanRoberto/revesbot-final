const test = require('node:test');
const assert = require('node:assert/strict');
const { domainFor } = require('../lib/houses');

test('resolve somente casas suportadas pelo agente de navegador', () => {
  assert.equal(domainFor('esportiva'), 'esportiva.bet.br');
  assert.equal(domainFor('bateu'), 'bateu.bet.br');
  assert.equal(domainFor('lotogreen'), null);
  assert.equal(domainFor('../invalid'), null);
});
