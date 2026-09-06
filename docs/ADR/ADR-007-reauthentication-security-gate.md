# ADR-007: Reauthentication and Security Gate

Status: decisão de desenho da Fase 2A; implementação pendente.

## Contexto

Uma sessão válida não basta para autorizar uma ação crítica nem comprova que o
usuário confirmou a operação recentemente. Refresh, atividade e metadados do client
não podem renovar confiança automaticamente. Futuras ações de dispositivos terão
consequências distintas e precisarão de políticas explícitas.

Lógica de recent authentication repetida por feature tende a produzir omissões e
regras divergentes. Biometria local e recuperação também podem virar bypass se não
houver distinção entre sinal local, prova de identidade e permissão do servidor.

## Decisão

Adotar o fluxo conceitual no monólito:

```text
request → authentication → session validation → Security Gate → Policy Engine
         → reauthentication requirement → execution → audit
```

O fluxo só alcança execution após `ALLOW`. `DENY` e `REAUTH_REQUIRED` encerram a
tentativa com auditoria; concluir reautenticação retorna ao Gate para nova avaliação.
Nenhum desses componentes é implementado neste ADR.

- Gate recebe usuário, sessão, ação registrada, recurso/device, ownership/permissões,
  métodos/nível de autenticação, prova recente, política e contexto de risco confiável.
- Policy Engine avalia regras versionadas, sem executar efeitos. O Gate devolve
  decisão estruturada `ALLOW`, `DENY` ou `REAUTH_REQUIRED`, com motivo, versão,
  correlação, requisitos, vínculos e prazo conforme [AUTH.md](../AUTH.md).
- Aplicar deny-by-default. Sem permissão, política, sessão válida ou método capaz de
  satisfazer a exigência, negar. Step-up não conserta ausência de ownership.
- Prova recente é verificada no servidor e expira em até 5 minutos por padrão.
  Refresh e `last_seen_at` não renovam esse prazo. Mudança relevante de contexto ou
  versão de segurança invalida a prova.
- Ações críticas usam desafio vinculado a usuário/sessão/ação/alvo/parâmetros;
  aprovação subsequente tem uso único e até 2 minutos, dentro dos prazos da prova.
  Consumir aprovação exige revalidar estado e política junto da execução.
- Senha recente pode atender operações de conta especificadas; ações remotas de
  alto risco permanecem negadas até definição de prova reforçada e consentimento.
  Não criar exceções locais do tipo `if password_recent` nas features.
- Logout da própria sessão e revogação automática de contenção não exigem step-up.
  Revogação individual/outras sessões pelo usuário usa a política de prova recente.
- Face ID/fingerprint são verificações do SO. O backend nunca recebe templates;
  uma flag local não autoriza. Uso futuro como step-up exige prova verificável de
  autenticador padrão registrado, vinculada ao desafio. Não substitui identidade.
- Recuperação não gera autorização geral; suas restrições também são aplicadas pelo
  Gate. Resets/mudanças/revogações invalidam elevações anteriores.
- Falha de banco/política ou auditoria durável crítica nega a execução. Registrar
  aprovação, execução e falha como eventos distintos e sem segredos.

## Consequências

Cada ação futura precisa de contrato, contexto e política explícitos, mas não
implementa autenticação por conta própria. A biblioteca/módulo de autorização será
parte do monólito: não há necessidade de microserviço ou motor externo nesta fase.

É necessário coordenar transações com revogação para que uma aprovação antiga não
autorize efeito novo. Efeito já commitado não é revertido; comandos externos futuros
exigem prazo, destinatário e deduplicação no executor. Nenhuma semântica exactly-once
é presumida.

Reautenticação cria fricção proporcional ao risco. Senha roubada e e-mail comprometido
não viram prova forte por serem reapresentados. Métodos fortes, trusted devices e
regras específicas de webcam/administração remota continuam pendentes de ADR e testes.

Alternativas rejeitadas: flags de senha recente em cada feature, timestamps do cliente,
refresh como autenticação recente e biometria local aceita sem evidência verificável.
Todas permitiriam divergência de política ou elevação sem garantia suficiente.

Consultar [THREAT_MODEL.md](../THREAT_MODEL.md) para replay, corrida de revogação,
clientes comprometidos e recuperação abusiva. ADRs 001–006 permanecem preservados.
