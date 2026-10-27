# Primeiro acesso e personalização

1. Entre como `admin`, com a senha privada definida no primeiro início.
2. Abra **Marca e agentes**. Informe nome, segmento, público, metas, fatos comerciais comprovados, tom, restrições e pilares. Defina website e CTA reais.
3. Escolha as três cores, idioma do conteúdo, moeda e fuso IANA (por exemplo `America/Sao_Paulo` ou `Europe/Lisbon`).
4. Envie seu logo em PNG/WebP/JPEG em Biblioteca da marca. Copie o ID retornado para Logo e salve. Outros elementos enviados ficam disponíveis para os agentes. Os elementos iniciais são vetores genéricos; substitua-os se não fizerem sentido para sua marca.
5. Personalize preferências de cada agente. Exemplos: copywriter com voz direta e sem urgência artificial; pesquisador focado em dúvidas do seu público; arte com composição limpa; analista priorizando conversas qualificadas e receita confirmada. O papel de viral/gancho é coberto pelo estrategista e copywriter; não existe promessa de viralização.
6. Cadastre fontes HTTPS que contenham `<main>` ou `<article>` e não redirecionem. Para radar, configure feeds RSS e os domínios permitidos. Fontes externas são dados não confiáveis; agentes não podem executar suas instruções.
7. Defina os horários de teste por canal, um HH:MM por linha. Novas vagas alternam entre os horários. Peças já associadas mantêm a reserva até reprogramação manual; salvar marca não altera conteúdo publicado.
8. Conecte as integrações que quiser e só então habilite geração automática. Uma instalação pode operar manualmente sem Codex, Meta ou Google.
9. Crie um briefing piloto. Confira se a arte, CTA, legenda e data refletem seu negócio. Aprovação humana é obrigatória. Edição posterior invalida a aprovação da versão anterior.

## Trocar senha administrativa

No console do **web**, como usuário `cml`, execute `python scripts/reset_password.py` em um checkout local; a imagem de runtime pode não conter scripts. Alternativa na imagem: execute o trecho abaixo pelo console interativo (não por logs), que pede a nova senha sem eco:

```python
import getpass, hashlib, secrets
from app import connect
password = getpass.getpass('Nova senha (mínimo 16 caracteres): ')
assert len(password) >= 16
salt = secrets.token_hex(16)
digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
with connect() as db:
    db.execute('UPDATE users SET salt=?,password_hash=? WHERE username=?', (salt,digest,'admin'))
```

Isso não revoga sessões já assinadas. Para incidente, pare os serviços e siga a orientação em SECURITY.md; não troque o segredo mestre sem migrar/recriptografar os dados.
