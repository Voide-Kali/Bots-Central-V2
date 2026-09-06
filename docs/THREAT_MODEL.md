# Threat Model — AUTH + SECURITY MODEL

Status: análise de desenho da Fase 2A. As mitigações deste documento são requisitos
futuros, não controles de autenticação já implementados ou validados. Preserva a
Foundation e não implementa contas, sessões, dispositivos ou clients.

## Escopo, ativos e limites de confiança

Ativos: identidade da conta, controle de e-mail, hashes de senha, material de sessão,
pepper de códigos humanos, recovery codes, decisões de autorização, auditoria e backups.
Integridade/privacidade de comandos, câmera e operações de dispositivos são ativos
futuros considerados para evitar decisões de autenticação incompatíveis com eles.

O monólito FastAPI é o único componente planejado com acesso de produto ao PostgreSQL.
O banco guarda estado autoritativo; clientes enviam alegações e credenciais a validar.
Um usuário registrado, endereço verificado ou device registrado não é automaticamente
confiável para agir sobre outros recursos. Metadados do cliente não são provas.

| Fronteira | O que não pode ser implicitamente confiado |
| --- | --- |
| Internet → backend | IDs, headers, origem declarada, tokens, relógio e identidade do cliente. |
| Backend → PostgreSQL | Permissões, disponibilidade, integridade transacional e cópias de dados exigem controle. |
| Backend → entrega de e-mail | Entrega pode falhar, atrasar, vazar ou cair em caixa postal comprometida. |
| App futuro → SO/armazenamento local | Flags biométricas e metadados não equivalem a prova verificada pelo servidor. |
| Backend → agent futuro | Autenticação da conta não resolve identidade, consentimento nem integridade do executor remoto. |
| Operação → logs/backups/admin | Acesso operacional não deve conceder poder irrestrito sobre identidade ou apagar evidências. |

Atacantes considerados: visitante anônimo automatizado, usuário malicioso autenticado,
portador de token roubado, invasor de e-mail/cliente/agent, leitor de backup e operador
interno abusivo. Comprometimento total do backend ou do SO está além da proteção que
uma senha/token pode oferecer, mas exige contenção, redução de segredos e recuperação.

As decisões concretas são definidas em [AUTH.md](AUTH.md),
[ADR-006](ADR/ADR-006-authentication-session-strategy.md) e
[ADR-007](ADR/ADR-007-reauthentication-security-gate.md). Não afirmar conformidade AAL,
resistência a phishing ou segurança de features ainda inexistentes.

## T01 — Stolen password

- **Threat:** atacante obtém senha por phishing, vazamento de outro serviço ou malware.
- **Impact:** criação de sessão como vítima e eventual troca de credenciais/controle de recursos.
- **Mitigation:** Argon2id para vazamento do servidor, bloqueio de senhas comprometidas,
  sinais de novo contexto, confirmação adicional quando exigida, gestão/revogação de
  sessões e notificação. Gate exige evidência específica para operações críticas.
- **Residual risk:** hashing não impede uso de senha já conhecida. E-mail e senha podem
  ser roubados juntos; repetir a senha não protege contra esse atacante. Poderes remotos
  de alto risco ficam negados até uma política de prova reforçada ser definida.

## T02 — Stolen access token

- **Threat:** bearer token é extraído do cliente, de telemetria ou de canal desprotegido.
- **Impact:** impersonação durante a validade, limitada apenas por permissões efetivas.
- **Mitigation:** bearer opaco de 256 bits, duração de 10 minutos, HTTPS, armazenamento
  mínimo, digest somente no servidor e lookup seguro por digest. Cada ação protegida
  revalida sessão, conta e `security_version`; revogação impede novos acessos de imediato.
- **Residual risk:** token roubado pode ser usado antes da expiração/detecção. Mudança de IP
  não distingue com certeza roubo; ações já autorizadas não são desfeitas retroativamente.

## T03 — Stolen refresh token

- **Threat:** atacante copia refresh de armazenamento, backup de cliente ou memória.
- **Impact:** obtenção de novos access tokens e persistência na conta.
- **Mitigation:** segredo aleatório, digest somente no servidor, armazenamento protegido
  do cliente, rotação a cada uso, prazos absoluto/ocioso e revogação de família/sessão.
- **Residual risk:** uso inicial do token roubado parece legítimo. Se a vítima não voltar
  a usá-lo, detecção de replay pode não acontecer antes da expiração absoluta.

## T04 — Refresh replay

- **Threat:** token de refresh consumido é reapresentado ou usado simultaneamente.
- **Impact:** duplicação de cadeias de sessão, persistência indevida ou DoS contra a vítima.
- **Mitigation:** transação serializa consumo/substituição; digests usados permanecem
  reconhecíveis até fim da família. Reuse reconhecido revoga família e sessão e gera
  evento/notificação. Token desconhecido não revoga sessão indicada por um atacante.
- **Residual risk:** retry legítimo após resposta perdida e concorrência entre abas podem
  causar revogação na política estrita. Cliente precisa serializar refresh; não há grace
  period nem promessa de retry transparente nesta baseline.

## T05 — Compromised email

- **Threat:** caixa postal, regra de encaminhamento ou provedor de entrega é comprometido.
- **Impact:** captura de códigos, recuperação indevida e ocultação de avisos da conta.
- **Mitigation:** desafios curtos e vinculados, consumo único, nenhuma mudança só por
  solicitar recuperação, grant restrito, revogação no reset e restrição de 24 horas.
  Recovery code independente é uma alternativa futura de prova; e-mail não é MFA forte.
- **Residual risk:** controle do e-mail pode bastar para reset na baseline. Cooldown e
  avisos não provam identidade; quem controla a caixa pode interceptar ambos. Exigir
  política reforçada antes de liberar ações remotas de alto impacto.

## T06 — Credential stuffing

- **Threat:** pares de credenciais vazadas são tentados em muitas contas e IPs.
- **Impact:** tomada de contas com senhas reutilizadas e sobrecarga de hashing/envio.
- **Mitigation:** senhas comprometidas bloqueadas, limites combinados por identificador,
  IP e contexto, backoff limitado e alertas agregados. PostgreSQL compartilha orçamento
  entre workers; não reiniciar contadores em cada nova tentativa/desafio.
- **Residual risk:** botnets com baixa taxa e credenciais corretas podem passar; medidas
  por IP têm efeitos sobre NAT/VPN. Detecção de risco demanda ajuste e monitoramento.

## T07 — Brute force

- **Threat:** adivinhação online de senhas/códigos ou cracking offline de hashes de senha.
- **Impact:** comprometimento de credenciais e consumo abusivo de CPU/memória.
- **Mitigation:** Argon2id com salt individual, comprimento permitido limitado, tokens de
  alta entropia, tentativas máximas e limites anteriores ao hashing. Configuração dos
  custos só no servidor e concorrência limitada fora do event loop.
- **Residual risk:** senha humana fraca continua vulnerável offline; limites não impedem
  todo DDoS. Tokens curtos numéricos não estão aprovados pela baseline de 256 bits.

## T08 — Enumeration

- **Threat:** diferenças de mensagem, status, tempo, resend ou limites revelam contas,
  estado de verificação ou recursos existentes.
- **Impact:** coleta de alvos e informação pessoal para ataques posteriores.
- **Mitigation:** respostas genéricas e custos comparáveis em fluxos anônimos, hash
  fictício com limites, política canônica de identificador e razões internas não expostas.
  Recurso alheio não gera desafio que confirme sua existência.
- **Residual risk:** tempo de rede e comportamento de e-mail não são perfeitamente
  indistinguíveis. Precisam de testes estatísticos e análise de canais laterais.

## T09 — Session fixation

- **Threat:** atacante faz a vítima autenticar usando identificador de sessão escolhido
  ou conhecido previamente por ele.
- **Impact:** associação da identidade da vítima a uma sessão controlada pelo atacante.
- **Mitigation:** IDs/secrets novos gerados no servidor após autenticação; tentativa
  pré-login tem escopo limitado e não se promove preservando material bearer. A elevação
  vincula a prova à sessão corrente sem aceitar timestamps/níveis do cliente.
- **Residual risk:** XSS, cookie injection e comprometimento do cliente podem roubar a
  nova sessão; renovação de identificador isolada não protege contra esses canais.

## T10 — CSRF considerations

- **Threat:** site malicioso induz navegador a enviar cookies autenticados em uma mudança
  de estado, inclusive login CSRF, refresh ou logout.
- **Impact:** ações não intencionais, vínculo da vítima à conta do atacante ou interrupção.
- **Mitigation:** futuro cliente web precisa de token CSRF apropriado, verificação de
  origem, cookies Secure/HttpOnly/SameSite com escopo restrito e nenhum efeito em GET.
  Autenticação bearer em header não é automaticamente enviada como cookie.
- **Residual risk:** SameSite e CORS não bastam isoladamente; topologia cross-site,
  subdomínios e fluxos de login precisam de teste antes de habilitar o cliente web.

## T11 — XSS considerations para futuro web client

- **Threat:** código malicioso executa na origem do futuro cliente web.
- **Impact:** leitura de access token em memória, ações como vítima, phishing local.
- **Mitigation:** codificação contextual, saneamento quando necessário, CSP e redução de
  scripts de terceiros; refresh HttpOnly, nenhum token persistido em localStorage,
  reautenticação vinculada à intenção e auditoria de ações críticas.
- **Residual risk:** HttpOnly não impede XSS de fazer chamadas com cookies. Step-up na
  mesma origem comprometida pode ser enganado; prevenir XSS continua necessário.

## T12 — Compromised mobile device

- **Threat:** malware, root/jailbreak ou posse de aparelho desbloqueado expõe a sessão.
- **Impact:** roubo de tokens e comandos executados com a autoridade do usuário.
- **Mitigation:** armazenamento protegido do SO, dados mínimos, revogação remota e
  prazos; biometria só local. Futuro step-up biométrico aceito pelo backend precisa
  provar desafio por autenticador padrão registrado, não enviar flag booleana.
- **Residual risk:** controle do SO pode abusar de credenciais não exportáveis enquanto
  o dispositivo está desbloqueado. Sem templates biométricos no backend não significa
  que um aparelho comprometido se tornou confiável.

## T13 — Compromised PC agent

- **Threat:** um futuro agent ou o SO do PC é controlado pelo atacante.
- **Impact:** execução local não autorizada, dados adulterados, vigilância e pivot para
  recursos acessíveis ao PC.
- **Mitigation:** futura identidade própria de agent, escopo por dispositivo, revogação,
  menor privilégio e verificação de destinatário/consentimento. Não distribuir refresh
  da conta aos agents; API autenticada da conta não autentica automaticamente um PC.
- **Residual risk:** o backend não pode garantir integridade de execução em SO comprometido.
  Protocolo, instalação, atualização e atestação de agent permanecem fora desta fase.

## T14 — Malicious registered device

- **Threat:** device futuramente registrado envia metadados falsos ou tenta operar em
  nome de outro usuário/device.
- **Impact:** acesso horizontal, abuso de confiança por registro e resultados falsos.
- **Mitigation:** registro não concede confiança geral; resolver ownership e ação no
  servidor, aplicar Gate por recurso e distinguir credenciais de conta e device.
- **Residual risk:** identidade válida só atribui origem, não garante honestidade do
  dispositivo. Device ID, enrollment e pairing ainda precisam de design separado.

## T15 — Replay of critical commands

- **Threat:** aprovação/desafio/comando capturado é repetido, reordenado ou aplicado a
  outro alvo/parâmetros.
- **Impact:** repetição de shutdown, ativação indevida de câmera ou mudanças destrutivas.
- **Mitigation:** aprovação vinculada a usuário, sessão, ação, alvo e parâmetros,
  validade curta e consumo único. Protocolo futuro exige ID único, prazo, destinatário,
  deduplicação e nova validação antes do envio/efeito permitido.
- **Residual risk:** quedas entre envio e confirmação tornam o resultado incerto;
  exactly-once não é presumido. Executor comprometido pode ignorar controles. Nenhum
  comando remoto é autorizado somente por existir este modelo.

## T16 — Leaked logs

- **Threat:** logs, tracing ou relatórios de erro expõem segredos e dados de segurança.
- **Impact:** sequestro de sessão, recuperação indevida e vazamento de informação pessoal.
- **Mitigation:** lista explícita de campos, nenhuma credencial/digest/header bruto,
  redaction complementar, acesso mínimo e retenção limitada. Não emitir configuração
  Compose renderizada com segredos, URLs ou conteúdo de `.env` em diagnósticos.
- **Residual risk:** SDKs/proxies e ferramentas operacionais podem vazar fora do logger
  do backend. Redaction por regex não garante cobertura universal; testar a cadeia inteira.

## T17 — Leaked database backup

- **Threat:** atacante lê backup contendo hashes, digests, identidades e auditoria.
- **Impact:** cracking offline, exposição de contas/metadados e preparação de ataques.
- **Mitigation:** Argon2id para senhas e alta entropia para tokens com digest; backups
  cifrados e chaves separadas, acesso mínimo, retenção e restauração controlada.
  Segredos de infraestrutura e pepper não ficam no banco de produto.
- **Residual risk:** hashes não tornam senhas fracas invulneráveis nem escondem metadados.
  Restauração pode reintroduzir sessões/tokens antigos: procedimento deve invalidar
  sessões, challenges e versões de segurança antes de reabrir acesso.

## T18 — Insider/admin risk

- **Threat:** operador abusivo consulta dados, altera estado/permissões ou apaga auditoria.
- **Impact:** impersonação, bypass de recuperação e ocultação de ações indevidas.
- **Mitigation:** menor privilégio, separação de funções, acesso operacional auditado,
  segredos separados e nenhum mecanismo oculto de login como usuário. Futuro suporte
  de recuperação exige prova, rastreabilidade e revisão independente.
- **Residual risk:** DBA/root com controle total pode alterar banco e evidências locais.
  Auditoria no mesmo PostgreSQL não é tamper-proof; exportação protegida e segregação
  operacional precisam de projeto antes de uso sensível.

## T19 — Account recovery abuse

- **Threat:** engenharia social, recovery code roubado ou flood tenta substituir a
  identidade e revogar sessões legítimas.
- **Impact:** tomada da conta, bloqueio da vítima e troca indevida de endereço/senha.
- **Mitigation:** grant de propósito limitado, códigos single-use armazenados só como
  digest, prova de endereço já verificado, nenhuma mutação pela solicitação, limites,
  revogação após conclusão e restrição temporária de ações críticas.
- **Residual risk:** recuperação somente por e-mail herda a segurança da caixa postal;
  um código roubado pode ser usado primeiro. Sem método aprovado restante, o usuário
  pode perder a conta. Não resolver isso com bypass manual de suporte.

## T20 — Bypass do Gate, IDOR e corrida de revogação

- **Threat:** acesso a recurso alheio, feature sem checagem central ou execução com
  decisão velha depois de mudança de permissão/revogação.
- **Impact:** escalada de privilégio e execução contrária à política vigente.
- **Mitigation:** deny-by-default, ownership server-side, decisão estruturada e
  versionada; checar sessão/versão/permissão ao consumir aprovação na mesma transação
  da mutação. Reautenticação não transforma usuário sem permissão em autorizado.
- **Residual risk:** transação commitada antes da revogação não é desfeita. Sistemas
  externos não compartilham atomicidade com PostgreSQL; protocolo futuro deve explicitar
  esse limite, e cada nova ação precisa de testes de autorização negativos.

## T21 — Comprometimento de pepper ou lookup de token

- **Threat:** atacante obtém o segredo HMAC de códigos humanos, explora lookup de digest
  como oracle ou tenta substituir token bearer por identificador conhecido.
- **Impact:** adivinhação offline facilitada de código de baixa entropia, enumeração de
  desafios e possível acesso indevido se o lookup não revalidar os vínculos server-side.
- **Mitigation:** HMAC-SHA-256 vinculado a challenge/purpose/conta/código, segredo fora
  de banco/repositório/logs, operação e rotação planejadas; IDs opacos, respostas
  genéricas, limites e revalidação de sessão/conta/versão após lookup por digest.
- **Residual risk:** pepper comprometido torna os códigos humanos já expostos no banco
  mais suscetíveis a brute force offline; rotação não muda códigos emitidos. Backend
  comprometido pode consultar ou alterar estado de token e exige contenção/revogação.

## T22 — Indisponibilidade e abuso de recursos de segurança

- **Threat:** flood esgota Argon2id, conexões PostgreSQL, locks, e-mail ou armazenamento
  de auditoria; falha operacional é explorada para pedir fallback permissivo.
- **Impact:** DoS, custos e tentativa de passar sem limites ou sem revogação verificável.
- **Mitigation:** limites compartilhados, tamanho de entrada, concorrência limitada,
  backoff sem manter threads, prazos e expurgo. Falha do banco/política/limitador
  nega operações protegidas; auditoria crítica é durável antes de efeito autorizado.
- **Residual risk:** segurança centralizada depende da disponibilidade do PostgreSQL.
  Limites também podem atingir usuários legítimos; capacidade e alertas precisam de
  validação de carga antes de habilitar autenticação real.

## Prioridades e evidências futuras

Antes da primeira implementação de auth: validar bibliotecas e custos de hashing,
atomicidade de consumo/rotação/revogação, invariantes de conta e respostas sem
enumeração. Antes de novos clients: verificar armazenamento, CSRF/XSS e sinais de
step-up. Antes de poderes remotos: resolver identidade/consentimento e replay no
executor. Os cenários de aceitação estão em [AUTH.md](AUTH.md).

Riscos que permanecem abertos: phishing/senha conhecida, e-mail como ponto de
recuperação, prova forte para operações remotas, perda total de fatores, SO/DBA
comprometidos, retenção de dados e falsos positivos de limites/reuse. Documentar
aceitação ou mitigação adicional antes de habilitar a superfície correspondente.
Não classificar todos como resolvidos porque uma especificação existe.

As fronteiras e impactos acima são análise do projeto. Referências de apoio para
decisões de sessão e checagem por requisição:
[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
e [OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
