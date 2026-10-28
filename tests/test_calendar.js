const assert=require('node:assert/strict');
const {zonedISO}=require('../static/calendar.js');
assert.equal(zonedISO('2026-10-28T12:30','America/Sao_Paulo'),'2026-10-28T15:30:00.000Z');
assert.equal(zonedISO('2026-10-28T12:30','Europe/Lisbon'),'2026-10-28T12:30:00.000Z');
assert.equal(zonedISO('2026-07-28T12:30','Europe/Lisbon'),'2026-07-28T11:30:00.000Z');
assert.equal(zonedISO('2026-10-28T12:30','Asia/Kolkata'),'2026-10-28T07:00:00.000Z');
assert.throws(()=>zonedISO('2026-03-08T02:30','America/New_York'),/não existe/);
assert.throws(()=>zonedISO('bad','UTC'),/inválidas/);
console.log('Calendar timezone checks passed.');
