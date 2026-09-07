# AUTH + SECURITY MODEL — Fase 2A

Status: desenho aprovado com implementação parcial. As primitivas Argon2id, a
canonicalização de e-mail e o serviço interno de registro estão implementados nas
Fases 2B.2 e 2B.3. Endpoints HTTP, login, sessões, tokens, desafios e entrega de
e-mail permanecem planejados. Requisitos marcados como **PLANNED** não devem ser
interpretados como funcionalidade disponível.

## 1. Escopo e decisões preservadas

Permanecem o monólito modular Python/FastAPI, Pydantic, SQLAlchemy/Alembic,
PostgreSQL como fonte de verdade e API versionada em `/api/v1`. Go para agents e
Flutter/Dart para mobile continuam decisões futuras, sem código nesta fase.
Não há Redis, serviço separado de identidade ou acesso direto de clientes ao banco.

Esta especificação complementa [ARCHITECTURE.md](ARCHITECTURE.md) e respeita
[SECURITY_MODEL.md](SECURITY_MODEL.md). As decisões estão em
[ADR-006](ADR/ADR-006-authentication-session-strategy.md) e
[ADR-007](ADR/ADR-007-reauthentication-security-gate.md). As ameaças e riscos
residuais estão em [THREAT_MODEL.md](THREAT_MODEL.md).

## 2. Princípios obrigatórios

| Princípio | Regra de desenho |
| --- | --- |
| Deny by default | Ação, recurso, política ou evidência desconhecida resulta em negação. |
| Least privilege | Sessão não concede permissões por si só; cada recurso requer autorização. |
| Defense in depth | Hashing, TLS, limites, revogação e auditoria protegem camadas distintas. |
| Explicit revocation | Estado server-side invalida inclusive access tokens ainda não expirados. |
| Short-lived credentials | Access tokens e desafios expiram; refresh não estende a sessão indefinidamente. |
| Secret minimization | Persistir digests; não duplicar segredos em logs ou metadados. |
| No custom crypto | Usar formatos, algoritmos e bibliotecas consolidados, sem primitivas próprias. |
| Auditability | Decisões e mudanças críticas devem deixar evidência sanitizada e correlacionável. |
| Centralized enforcement | Security Gate concentra exigências; features não decidem autenticação recente. |
| Safe failure | Falha de banco, política ou validação nunca concede acesso. |
| Recovery is not a bypass | Recuperação tem finalidade limitada, restrições e revogação próprias. |

## 3. Modelo conceitual da conta

Os nomes a seguir descrevem informações e invariantes, não um esquema SQL.

| Conceito | Informação e responsabilidade |
| --- | --- |
| User | `user_id` opaco, estável e gerado pelo servidor; não é e-mail, Device ID nem autorização. |
| Email | Endereço original, chave de comparação, `verified_at` e eventual alteração pendente. Inicialmente um e-mail principal. |
| Password credential | Hash Argon2id codificado, versão da política, `changed_at`; nunca senha recuperável. |
| Email verification | Evidência de controle do endereço específico; não comprova identidade civil. |
| Account status | `pending_verification`, `active`, `locked` ou `disabled`. |
| Timestamps | `created_at` e `updated_at` em UTC, definidos pelo servidor. |
| Security state | Versão de segurança, exigência de troca de senha, restrição de recuperação, motivo/prazo de bloqueio e contexto de risco. |

**CURRENT — registro interno:** a identidade de e-mail é validada por biblioteca
apropriada sem consulta DNS de entregabilidade. Somente whitespace externo é removido.
`email_display` preserva o endereço aceito para apresentação; `email_canonical` é a
identidade de comparação, com local-part ASCII em minúsculas e domínio validado e
normalizado. Não retirar pontos ou sufixos `+`, nem aplicar regras específicas de
provedores. Essa comparação é uma escolha de produto, não uma afirmação sobre todos
os servidores de e-mail; local-parts sensíveis a caixa e suporte EAI precisam de
revisão explícita. PostgreSQL reserva `email_canonical` de modo atômico para impedir
contas concorrentes com o mesmo identificador. Todas as operações atuais usam essa
política de comparação.

| Estado | Acesso e transição permitidos |
| --- | --- |
| `pending_verification` | Apenas fluxos limitados de verificação/abandono; não recebe sessão de uso geral. Verificação válida permite `active`. |
| `active` | Pode autenticar; autorização ainda depende de sessão, estado de segurança e política. |
| `locked` | Bloqueio de segurança reversível, com motivo e critérios de saída. Nega acesso e refresh; revoga sessões existentes. |
| `disabled` | Suspensão persistente por decisão autorizada. Nega acesso e recuperação automática; não é revertida por código de e-mail. |

`active → locked/disabled` revoga sessões e desafios relacionados na mesma mudança
de estado. Desbloquear não ressuscita tokens ou sessões: exige novo login. Uma conta
sem e-mail verificado volta a `pending_verification`, nunca a `active`, ao sair de
um bloqueio. Reabilitação administrativa e expurgo de cadastros abandonados são
procedimentos futuros que exigem decisão própria.

Falhas comuns de login usam cooldown, não bloqueio permanente da conta provocado
por qualquer visitante. Um sinal de risco validado pode exigir nova verificação ou
bloqueio temporário. Estado da conta e estado de segurança são ortogonais: uma conta
ativa pode estar em `recovery_restricted` e não poder executar ações críticas.

## 4. Senhas

**CURRENT — password security:** Argon2id é obrigatório, com salt aleatório por hash
e perfil explícito: `time_cost=3`, `memory_cost=65536` KiB, `parallelism=4`,
`hash_len=32`, `salt_len=16` e `encoding=UTF-8`. A biblioteca armazena hash, salt e
parâmetros no formato codificado. Não armazenar plaintext, senha reversivelmente
cifrada ou hash rápido de senha; a verificação usa somente a função da biblioteca.

Criação e alteração aceitam 15 a 1024 caracteres Unicode. Verificação aplica somente
o máximo técnico de 1024 caracteres, sem mínimo, para preservar compatibilidade com
hashes de política anterior. Não há trim, normalização Unicode, case folding ou
truncamento; espaços e cada sequência Unicode fornecida são significativos. Não há
regras de composição. `VerifyMismatchError` e `InvalidHashError` retornam `False`;
`VerificationError` genérico torna-se erro interno de domínio, e falhas de plataforma
ou parâmetros não são mascaradas. Rehash é apenas uma decisão da biblioteca e hash
corrompido não é tratado como atual. Ver [PASSWORD_SECURITY.md](PASSWORD_SECURITY.md).

**PLANNED — login ou integração HTTP:** bloquear senhas comuns/comprometidas sem
enviá-las a terceiros; aplicar limites de corpo e de carga antes de hashing; executar
hashing fora do event loop com concorrência limitada; usar verificação fictícia de
custo comparável para conta inexistente; e medir canais de tempo e regressões. Esses
requisitos não estão implementados e não há login ou transporte HTTP nesta fase. O
rehash bem-sucedido poderá gravar hash novo com salt novo de modo atômico em fluxo
futuro; isso não equivale a troca de senha nem autenticação recente.

## 5. Desafios de e-mail e códigos de segurança

### Dois materiais, dois contratos

Desafios de e-mail usam dois materiais distintos. Cada challenge possui identificador
opaco, purpose, usuário/conta quando conhecido, endereço alvo, contexto/sessão quando
aplicável, criação, expiração, tentativas, consumo e invalidação. O servidor valida
prazo, finalidade e todos os vínculos antes de qualquer transição.

| Material | Formato e persistência | Uso proposto |
| --- | --- | --- |
| High-entropy link token | 256 bits CSPRNG, base64url; persistir apenas digest SHA-256. | Link de e-mail de uso único, TTL curto e vínculo a purpose/contexto. |
| Human-entered email code | 8 dígitos decimais, exibido como `1234 5678`; persistir apenas digest HMAC-SHA-256 vinculado ao challenge. | Código digitável para verificação, confirmação de contexto suspeito ou recuperação conforme política. |

O link token tem entropia suficiente para que SHA-256 simples seja um digest aceitável
no banco. O código humano tem aproximadamente 27 bits de espaço de busca e **não**
pode usar SHA-256 simples: o banco permitiria adivinhação offline. Seu digest é
HMAC-SHA-256 de uma codificação canônica com `challenge_id`, `purpose`, `user_id` ou
identificador de conta quando conhecido e o código normalizado de oito dígitos. O
segredo HMAC/pepper fica fora do PostgreSQL, repositório, imagem e logs. A Fase 2B.4B
implementa a fundação de geração/validação de material, framing, HMAC-SHA-256,
comparação constant-time e keyring versionado; [EMAIL_VERIFICATION.md](EMAIL_VERIFICATION.md)
e ADR-008 definem o contrato completo. Emissão, reenvio, consumo, rotação operacional,
locks e transições de conta continuam sem implementação.

Ao verificar código, o servidor normaliza somente separadores de apresentação, requer
exatamente oito dígitos, recompõe o HMAC usando o challenge carregado por ID e compara
por construção/biblioteca apropriada em constant-time quando aplicável. Não inventar
concatenação ambígua, comparação manual ou primitivas próprias. O lookup é por ID de
challenge e contexto; código não é índice global.

Ambos os materiais são single-use e consumidos atomicamente: uma única requisição
concorrente vence. Link token expira em no máximo 15 minutos. Código humano tem TTL
baseline de aproximadamente 10 minutos, no máximo 5 tentativas por challenge e resend
cooldown mínimo de 60 segundos. Os limites globais por conta/IP da seção 13 continuam.
Reenvio gera material novo e invalida o challenge anterior do mesmo usuário, purpose e
contexto; não zera orçamento de abuso. Prazo não é prolongado por tentativa. Conta
bloqueada/desabilitada não é reativada pelo consumo.

| Purpose | Material permitido e validade | Vínculo obrigatório e efeito |
| --- | --- | --- |
| `email_verification` | Link ou código humano; até 10 min para código, 15 min para link. | Conta pendente e endereço exato; marca somente esse endereço como verificado. |
| `suspicious_login` | Código humano; até 10 min. | Usuário e tentativa pré-autenticada por senha; registra apenas `mailbox_confirmed`/`context_confirmed` antes de criar sessão. |
| `account_recovery` | Link ou código humano; até 10 min. | Conta e e-mail já verificado; permite somente iniciar conclusão restrita de recuperação. |
| `critical_change` | Link ou código humano; até 5 min. | Usuário, sessão, ação, recurso e parâmetros imutáveis; evidência adicional exigida pelo Gate. |

A resposta pública de solicitação de verificação, cadastro ou recuperação é genérica,
independente de a conta existir, estar verificada ou bloqueada. Erros de token inválido,
expirado ou consumido não revelam o estado da conta. Não criar lockout por mera
solicitação de recuperação. Estas regras se apoiam em
[OWASP Forgot Password](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

E-mail é controle de caixa postal, confirmação adicional e canal de recuperação.
Código de e-mail não é MFA forte, autenticação resistente a phishing ou prova suficiente
para webcam e futuras ações remotas críticas. Em login suspeito, ele registra apenas
`mailbox_confirmed`/`context_confirmed`, sem elevar para nível forte de autenticação.
Webcam e operações remotas de alto risco permanecem `DENY` até ADR de autenticador
reforçado/consentimento. Passkeys/WebAuthn ou outro autenticador padrão resistente a
phishing devem ser avaliados antes de habilitar tais poderes.
NIST não aceita e-mail como autenticador out-of-band; o projeto reconhece essa
limitação em vez de promover seu nível de garantia.
[NIST Authenticator Requirements](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/).

### Envio conceitual

Uma interface interna de entrega recebe destinatário autorizado, purpose, template
permitido, material efêmero, prazo e referência de correlação. Retorna aceitação de
entrega ou falha sanitizada; entrega não é evidência de posse nem autenticação.
Não expor envio arbitrário de texto/HTML, destinatário ou template ao cliente.
Adaptador/provedor, credenciais de envio e contratos HTTP ficam para implementação
posterior; nenhuma integração Gmail está decidida ou implementada.

Baseline: persistir o digest antes de enviar, manter plaintext só em memória e apagá-lo
ao encerrar a tentativa. Não manter link token ou código em fila, outbox ou log para
facilitar retry. Falha de entrega exige nova tentativa com material novo, dentro dos mesmos limites;
não muda o estado da conta nem retorna segredo ao solicitante. Se futuramente for
necessária entrega durável, registrar decisão de armazenamento protegido e retenção.

Links futuros usam origem configurada e permitida, nunca `Host` arbitrário ou
redirecionamento do cliente. Não colocar tokens na query de API, telemetria ou logs;
uma página dedicada poderá receber token em fragmento e enviá-lo em corpo protegido,
com `no-store`, política de referrer e sem recursos de terceiros. Abrir um link com
GET não consome o token: scanners de e-mail não podem executar a mudança. O contrato
web exato precisa ser validado antes de qualquer envio real.

## 6. Sessões server-side

PostgreSQL é a fonte autoritativa. Cada acesso protegido resolve o bearer access token
opaco, sessão e conta no banco. Não usar cache positivo de autorização na primeira
implementação. Banco indisponível implica falha segura; não há token autovalidável de
fallback. O health público da Foundation continua com seu contrato atual.

| Informação conceitual | Semântica |
| --- | --- |
| `session_id`, `user_id` | IDs opacos gerados no servidor; o primeiro não é uma credencial bearer. |
| `client_metadata` | Tipo/nome/versão de cliente e SO, declarados e sanitizados; não são identidade confiável do dispositivo. |
| `created_at`, `last_seen_at` | UTC no servidor; último uso tem atualização limitada e precisão documentada. |
| `expires_at`, `idle_expires_at` | Prazo absoluto e prazo por inatividade; ambos verificados no servidor. |
| `revoked_at`, `revocation_reason` | Revogação monotônica; reason enumerado e sanitizado, sem texto secreto. |
| `authentication_level`, `authentication_methods` | Evidência efetivamente validada no servidor, não alegações escolhidas pelo cliente. |
| `recent_reauthentication` | Método, instante, expiração, contexto, versão de segurança e referências de challenges/grants. |
| `security_version` | Versão da conta no momento da autenticação; divergência invalida sessão/elevação. |
| `refresh_family` | Cadeia de refresh associada exclusivamente à sessão. |
| `risk_context` | Sinais limitados, razão de restrições e referência da política aplicada. |

Baseline proposta: sessão com 30 dias absolutos e 7 dias de inatividade. Um refresh
tem validade até o menor desses prazos; rotação ou uso não ultrapassa `expires_at`.
O prazo de inatividade usa apenas atividade autenticada válida. Atualizar `last_seen_at`
e prazo ocioso no máximo uma vez por minuto; esse atraso conservador pode antecipar
expiração em até um minuto. Requisições inválidas nunca mantêm sessão viva.

Criar identificador novo após login bem-sucedido; não aceitar ID pré-login escolhido
pelo cliente. Credencial correta em contexto suspeito gera apenas tentativa limitada
de desafio, não sessão normal. Confirmação de e-mail isolada também não cria sessão.
Renovação de refresh não eleva nível nem renova autenticação recente. Mudança de
contexto relevante invalida a elevação, mas IP/User-Agent isolados não identificam
com segurança um dispositivo nem determinam bloqueio permanente.

`authentication_level` começa com `password_authenticated`. Confirmação adicional
de e-mail fica registrada como método/contexto, sem virar nível forte. Futuro nível
baseado em autenticador resistente a phishing exige outra decisão. Não ordenar métodos
por um número arbitrário: o Gate exige conjuntos explícitos de evidências. Grants de
recuperação não são sessões normais e nunca recebem esse nível.

## 7. Access token opaco

Decisão: bearer access token opaco de 256 bits CSPRNG, com duração inicial aproximada
de 10 minutos. O plaintext existe apenas no retorno controlado ao cliente e durante a
verificação; nunca é persistido no banco, incluído em URL, registrado em logs ou
reconstruído a partir de `session_id`. PostgreSQL guarda somente digest SHA-256, com
vínculo server-side a `session_id`, `user_id`, criação e expiração. Alta entropia torna
o digest SHA-256 apropriado para esse material aleatório; não é a construção usada para
código humano ou senha.

Ao receber o bearer token, o servidor valida formato/tamanho, calcula o digest com a
função padrão da biblioteca e faz lookup seguro por digest. O registro encontrado deve
pertencer a uma sessão e conta ainda válidas; a comparação de material quando necessária
usa construção/biblioteca apropriada em constant-time. Não criar algoritmo próprio,
usar token como ID de sessão ou confiar em metadados do cliente. Lookup desconhecido
tem resposta genérica e limites para não servir como oracle.

Toda requisição protegida revalida no PostgreSQL `security_version`, account status,
sessão, `user_id`, expiração ociosa/absoluta e revogação antes da autorização. Revogar
a sessão invalida imediatamente seus access tokens, mesmo que o prazo de 10 minutos não
tenha passado. Access token não carrega dados de autorização, e-mail, identificador de
dispositivo, contexto de risco ou prova de reautenticação; isso vem do estado server-side.

Token é enviado somente por HTTPS em header Authorization fora de desenvolvimento local
e nunca em URL. Armazenamento local segue a política do cliente na seção 9. Não há
JWT, JWS, RS256, `kid`, claims de issuer/audience, parsing JWT ou rotação de chaves JWT
no baseline inicial. JWT pode ser reconsiderado somente se surgir necessidade concreta
de validação distribuída/offline entre serviços, acompanhada de ADR, ameaça e operação
de chaves próprios.

## 8. Refresh token: rotação, concorrência e replay

Refresh é segredo bearer opaco de 32 bytes CSPRNG, armazenado no servidor
somente como digest SHA-256. Registro conceitual inclui sessão/família, geração,
expiração, consumo, substituição e revogação. Nunca aceitar digest como credencial.
O access token não serve como prova de reautenticação.

Fluxo proposto, em uma transação no PostgreSQL:

1. Aplicar limites e validar formato/tamanho antes de consultar o digest.
2. Identificar a família pelo digest armazenado, não por ID de sessão fornecido sem
   prova. Serializar pela conta/sessão/família com ordem de locks consistente com
   revogações e troca de credenciais; reler estado depois de obter os locks.
3. Se conta, sessão ou token estiverem expirados/revogados, negar sem emitir tokens.
4. Se o digest é do token atual ainda não usado, marcar consumo e gerar sucessor
   aleatório. Gravar somente seu digest e vínculo; invalidar o anterior no mesmo commit.
5. Preparar novo access token e retornar ambos apenas depois do commit. Falha/rollback
   não publica credenciais; nenhuma atualização é parcial.
6. Digest já consumido reconhecido indica reuse suspeito: revogar toda a família e
   sua sessão, invalidar elevações, registrar `refresh_reuse_detected` e notificar.
   A revogação deve ser commitada mesmo que a resposta seja de erro.
7. Digest desconhecido não permite descobrir nem revogar uma sessão arbitrária;
   negar genericamente, limitar e registrar sinais agregados de abuso.

Guardar digests consumidos até o término absoluto da família para reconhecer replay
de qualquer geração, não apenas a anterior. Limites de frequência contêm o crescimento;
depois do prazo absoluto, eliminar digests segundo retenção e manter só eventos
necessários. Reuse não reativa tokens expirados. Rotação/detecção se baseia na
[RFC 9700, seção 4.14](https://www.rfc-editor.org/info/rfc9700/), aplicada aqui como
padrão de segurança, não como declaração de implementação OAuth.

Baseline estrita: sem grace period nem reenvio de refresh plaintext armazenado.
Cliente serializa refresh por sessão, inclusive entre abas no futuro. Duas chamadas
com o mesmo token produzem no máximo um sucessor; a segunda pode revogar a sessão
inteira. Perda da resposta depois do commit exige novo login, pois repetir o token
consumido é indistinguível de replay. Esse custo de disponibilidade é deliberado.
IP/cliente idêntico não permite ignorar reuse. O atacante que usou primeiro pode ter
acesso até a detecção; rotação não elimina esse risco.

## 9. Gestão, revogação e armazenamento no cliente

Futura visualização exige sessão válida e mostra somente sessões da própria conta:
nome/tipo de cliente, data de criação, último uso e indicação da sessão atual. Não
expor tokens, digests ou contexto bruto de risco. Metadados são descritivos e podem
ser falsificados. Localização aproximada não será coletada por padrão; sua adoção
exige justificativa de privacidade, precisão, retenção e fonte. Não usar GPS para isso.

| Evento | Política de revogação proposta |
| --- | --- |
| Logout | Revogar sessão atual/família e apagar credenciais locais; não exigir reautenticação para sair. |
| Revogar sessão individual | Somente sessão própria, conforme Gate; invalidar família e elevação. |
| Revogar todas as outras | Sessão chamadora permanece, as demais e suas famílias são revogadas atomicamente. |
| Troca de senha autenticada | Exigir reautenticação; atualizar credencial e versão, revogar todas as sessões, inclusive atual; novo login. |
| Password reset/recuperação | Revogar todas as sessões/famílias/grants antigos, notificar e exigir novo login. |
| Alteração de e-mail concluída | Verificar novo endereço, exigir prova recente e confirmação do antigo quando disponível; trocar atomicamente e revogar todas as sessões. |
| Bloqueio/desabilitação/comprometimento | Revogar todas as sessões e invalidações relacionadas; não esperar expiração de access token. |

Revogar individualmente/outras sessões requer prova recente por padrão. Logout atual
e revogação automática de contenção pelo servidor não dependem de step-up. Política
não pode transformar dificuldade de reautenticação em impossibilidade de logout.
Uma sessão revogada nunca volta a ativa; excluir cookie local não basta.

Mudança de e-mail mantém o endereço antigo como identidade até confirmar a troca.
Vincular desafio ao novo endereço e ao pedido; não alterar ambos após confirmação.
Notificar endereço antigo e novo sem credenciais. Perda do antigo leva à recuperação
restrita, não à aceitação silenciosa de outro endereço. Novo e-mail não é destino
válido para recuperação de uma conta ainda vinculada ao anterior.

Mobile futuro: refresh no armazenamento protegido do SO, access preferencialmente
em memória; excluir de backups/telemetria quando suportado. Não prometer proteção
contra SO comprometido. Agents terão identidade/protocolo próprios em fase futura:
credenciais de conta não serão instaladas em cada PC como identidade do agent.

Web futuro: refresh em cookie `Secure`, `HttpOnly`, `SameSite` restritivo, sem Domain
amplo e com escopo definido na revisão do cliente. Access em memória, sem persistência
em localStorage. Requisições que usam cookies, inclusive login/refresh/logout,
exigem defesa CSRF (token apropriado e validação de origem); não alterar estado via
GET. CORS não substitui CSRF. Essa combinação é condicionada à futura topologia web,
seguindo [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## 10. Recuperação de conta

Solicitação por identificador sempre recebe resposta genérica. Recuperação por
e-mail usa somente o endereço principal já verificado. Prova válida cria grant curto
de 10 minutos e uso único, vinculado a usuário/purpose/operação de reset; não emite
sessão de uso geral nem autoriza ações de dispositivos. Mera solicitação nunca
revoga sessões, bloqueia conta ou invalida senha. Não usar perguntas de segurança.

Recovery codes: gerar lote inicial proposto de 10 códigos independentes de pelo
menos 128 bits CSPRNG, em formato transcritível com separadores. Mostrar plaintext
uma única vez, em resposta `no-store`, sem logs ou envio automático por e-mail.
Guardar apenas digests SHA-256 e estado de consumo/geração. O ID de conta/desafio
limita o contexto de busca; código não carrega autoridade fora da recuperação.
Consumo é atômico, limitado por tentativas e single-use. Regeneração com reautenticação
invalida todo o lote anterior. Perda da resposta de geração exige gerar outro lote,
pois não há recuperação de plaintext pelo servidor.

Um recovery code válido pode substituir prova de e-mail para o reset restrito se a
caixa postal foi perdida. Recuperar também o endereço exige comprovar o novo e-mail
e política adicional; essa transferência não será habilitada até resolver os critérios
de prova e contestação. Trusted sessions/devices são possíveis evidências futuras,
não bastando um ID, metadado ou alegação de confiança. Não há fallback automático
de suporte/admin que ignore evidências.

Conclusão sensível deve, em uma transação, consumir o grant/código, trocar a senha,
incrementar versão de segurança, revogar todas as sessões e desafios antigos e
registrar auditoria. Invalidar lotes de recovery codes anteriores após recuperação
concluída; emitir novo lote somente por fluxo autorizado posterior. Exigir login
normal e enviar notificação ao e-mail verificado anterior, sem nova senha ou tokens.

Política inicial proposta: `recovery_restricted` por 24 horas após conclusão sensível.
Bloquear mudanças adicionais de e-mail, geração de recovery codes e ações remotas
críticas nesse período; permitir logout, contenção/revogação e acesso às informações
de segurança conforme Gate. Login ou confirmação repetida do mesmo e-mail não remove
a restrição. A configuração desse prazo exige revisão; não constitui prova adicional
de identidade. Encerrado o prazo, ações críticas continuam exigindo reautenticação.
Se conta estiver `disabled`, o fluxo não a reabilita; `locked` só sai mediante política
de recuperação que explicitamente aceite aquele motivo de bloqueio.

Comprometimento de e-mail continua podendo permitir reset na baseline. Recovery
não é resistente a phishing e não deve liberar poderes remotos de alto risco até
definir evidência mais forte. Sem e-mail, recovery code ou futuro método aprovado,
recuperação pode ser impossível; isso é preferível a um bypass administrativo oculto.

## 11. Reautenticação recente e biometria

Autenticação recente é uma prova nova validada pelo backend, não `last_seen_at`,
refresh, horário do cliente, presença de cookie ou access token renovado. Baseline:
janela máxima de 5 minutos desde prova explícita de senha, desde que sessão, versão
de segurança e contexto permaneçam válidos. O Policy Engine pode exigir janela
menor, evidência adicional ou negar enquanto não houver método forte suficiente.

Registrar no servidor método, instante, expiração, usuário/sessão, ação/classe
permitida, alvo, parâmetros relevantes e contexto de risco. Mudança de senha/e-mail,
revogação, recuperação ou mudança relevante de risco invalida a prova. Limites de
tentativas de reautenticação não renovam janela nem elevam a sessão.

Para operação crítica, o Gate emite desafio opaco de até 5 minutos vinculado a
usuário/sessão/ação/alvo e digest dos parâmetros de efeito. Prova bem-sucedida permite
reavaliar a política e criar autorização de execução single-use de até 2 minutos,
nunca além da prova/sessão/desafio. Trocar destinatário, dispositivo ou parâmetros
exige nova avaliação. Concluir o desafio não executa automaticamente a ação.

Face ID/fingerprint são avaliados pelo sistema operacional. Bots Central nunca
recebe imagem, template, amostra biométrica ou decisão biométrica bruta para comparar.
Biometria pode desbloquear um segredo local e sinalizar intenção; uma flag enviada
pelo app não é prova confiável de step-up para o servidor. Futuro uso para satisfazer
o Gate exige prova criptográfica verificável, vinculada a desafio/sessão/ação, por
autenticador padrão previamente registrado. Até isso existir, biometria local sozinha
não substitui identidade da conta nem reautenticação exigida pelo backend.

## 12. Security Gate e Policy Engine

Fluxo conceitual obrigatório para operações protegidas:

```text
request → authentication → session validation → Security Gate → Policy Engine
                                                           ↓
                                              reauthentication requirement
                                                           ↓
                                    ALLOW → execution → audit
                                    DENY / REAUTH_REQUIRED → audit → resposta
```

Retorno de uma reautenticação volta ao Gate para avaliação completa. Os blocos são
responsabilidades internas do mesmo monólito; não representam microserviços. Login,
verificação e recuperação têm políticas públicas limitadas por finalidade/abuso,
não um bypass que permite execução de ações de produto.

| Responsabilidade | Limite |
| --- | --- |
| Authentication | Valida evidência/token; não determina permissão sobre recurso. |
| Session validation | Lê conta/sessão vigentes e expiração/revogação no PostgreSQL. |
| Security Gate | Reúne contexto confiável, exige decisão e coordena step-up/auditoria. |
| Policy Engine | Avalia regras explícitas e versionadas; não chama devices, envia e-mail ou executa ação. |
| Execution | Executa apenas ação autorizada e ainda válida; verifica invariantes transacionais. |
| Audit | Registra tentativa, decisão, consumo e resultado sem segredos. |

Entradas do Gate: authenticated user, session, action registrada, target resource/device,
nível/métodos de autenticação, recent reauthentication, policy/version, ownership ou
permissão atual e contexto de risco/segurança. Identidade, autorização, relógio e provas
vêm de componentes server-side. IDs e metadados enviados pelo cliente são apenas
solicitações; o backend resolve recurso e escopo antes de decidir.

Decisão estruturada conceitual:

| Campo | Conteúdo |
| --- | --- |
| `decision` | `ALLOW`, `DENY` ou `REAUTH_REQUIRED`. |
| `decision_id`, `policy_version` | Referências de correlação e regra avaliada. |
| `reason_code` | Motivo enumerado interno; resposta pública não revela existência de recurso alheio. |
| `requirements` | Métodos aceitos, janela e contexto exigidos quando há possibilidade de step-up. |
| `binding`, `valid_until` | Usuário, sessão, ação, recurso, parâmetros e prazo de eventual aprovação. |
| `audit_context` | Referências sanitizadas, nunca payloads/segredos arbitrários. |

Prioridade: conta/sessão inválida, recurso alheio, política ausente ou restrição
proibitiva resulta em `DENY`. Somente usuário elegível à ação, com prova insuficiente
mas satisfazível por método suportado, recebe `REAUTH_REQUIRED`. Quando nenhuma
prova disponível atende à política, negar. Senha recente não transforma negação de
permissão em autorização. Não distribuir `if password_recent` pelas features.

| Exemplo futuro | Exigência conceitual; não habilita a feature |
| --- | --- |
| Trocar senha/e-mail ou gerar recovery codes | Prova recente, vínculos e confirmações específicas das seções 9–11. |
| Revogar sessão individual/outras | Propriedade e prova recente; logout atual permanece permitido sem step-up. |
| Webcam, shutdown/restart e administração remota | Política específica de recurso, consentimento e prova reforçada a definir; `DENY` até essa definição. |
| Remoção de dispositivo | Permissão sobre alvo, prova recente e confirmação vinculada à operação; identidade de device ainda futura. |

`ALLOW` não é credencial reutilizável nem elimina condições de corrida. Para mutações
no PostgreSQL, revalidar sessão/versão/permissão ao consumir aprovação na transação
da ação, com serialização compatível com revogação. Revogação concluída antes dessa
checagem impede execução; não desfaz operação já commitada. Para comandos remotos
futuros, exigir ID único, prazo, destinatário e proteção contra replay no executor,
além de nova validação antes do envio. Não prometer exactly-once ou cancelamento de
efeito já executado; protocolo e teste desse limite antecedem qualquer agent.

## 13. Rate limit e abuso no monólito

Estado compartilhado de contadores/janelas/cooldowns no PostgreSQL, com atualizações
atômicas e expurgo por prazo. Limitadores em memória podem proteger um processo,
mas não substituem limites globais quando houver vários workers. Definir limites
antes de hashing, envio e locks caros; parametrização validada não permite valores
ilimitados em produção. Nenhuma dependência Redis é necessária nesta fase.

Baselines propostas para testes; aplicar dimensões em conjunto, não como alternativas:

| Fluxo | Conta/identificador | IP confiável de origem | Sessão/contexto e contenção |
| --- | --- | --- | --- |
| Login | 5 falhas/15 min | 30 tentativas/min | Backoff após falhas: 1, 2, 4… até 60 s; desafio por risco. |
| Envio de código | 5 envios/h por purpose e 10/h somados | 20 envios/h | Reenvio mínimo de 60 s; não reiniciar orçamento no novo desafio. |
| Validação de código | 10 falhas/15 min por purpose | 30 tentativas/15 min | 5 erros/desafio; invalidar ao esgotar. |
| Recovery | 3 solicitações/h; 5 falhas/15 min na prova | 10 solicitações/h; 20 provas/15 min | 5 erros/grant; solicitação nunca bloqueia permanentemente a conta. |
| Refresh | 120 tentativas/min | 300 tentativas/min | 10/min por sessão conhecida; cliente serializa chamadas. |
| Reauthentication | 10 falhas/15 min | 30 tentativas/15 min | 5 falhas/15 min por sessão; invalidar desafio esgotado. |

Conta desconhecida usa chave de identificador pseudonimizada e mesmos limites de
conta conhecida, sem indicar existência. Não usar `session_id` arbitrário como prova
para revogar/penalizar vítima. IP só deriva da conexão ou de proxy explicitamente
confiável; não confiar em `X-Forwarded-For` livre. IP compartilhado, NAT, VPN e redes
móveis geram falsos positivos: revisar thresholds com métricas e respostas genéricas.

Cooldown é prazo persistido e resposta limitada, não manter threads dormindo.
Orçamento expirado pode informar espera sem expor estado de conta. Contadores de
falhas relevantes não são eliminados por reenvio ou troca de identificador de desafio.
Considerar abuso distribuído/credential stuffing por sinais agregados e alertas.
Se limitador autoritativo falhar, negar autenticação/refresh/recuperação cara de forma
temporária; não liberar sem limite. Falha de observabilidade não justifica bypass.

## 14. Auditoria e notificações

Eventos mínimos propostos:

| Evento | Registro de interesse |
| --- | --- |
| `login_success`, `login_failure` | Contexto aprovado ou falha relevante, sem credencial/identificador bruto não resolvido. |
| `logout`, `session_created`, `session_revoked` | Sessão, motivo enumerado, ator e resultado. |
| `refresh_reuse_detected` | Família/sessão, detecção e revogação; nunca o digest/token apresentado. |
| `email_verification_completed`, `email_changed` | Mudança e referências internas; sem endereços completos por padrão. |
| `password_changed`, `password_reset` | Versão de segurança e abrangência da revogação. |
| `recovery_initiated`, `recovery_completed`, `recovery_code_used` | Tipo de prova e resultado restrito; nenhum código/grant bruto. |
| `reauthentication_success`, `reauthentication_failure` | Método, ação/contexto vinculado e resultado. |
| `security_gate_denial`, `reauthentication_required` | Ação, política, motivo e correlação. |
| `critical_action_approved`, `critical_action_executed`, `critical_action_failed` | Separar autorização de efeito, incluindo consumo/idempotência e resultado. |

Envelope mínimo: ID de evento, UTC server-side, tipo, ator/sessão quando conhecidos,
action/target opacos, resultado, reason code, correlation/decision ID e versão da
política. IP completo e localização não entram por padrão; retenção de sinal de rede
pseudonimizado/truncado precisa de finalidade definida. Sanitizar controles de linha,
tamanhos e metadados não confiáveis contra log injection.

Nunca guardar senha, token/código plaintext, digest de credencial, recovery code,
Authorization header, DATABASE_URL com segredo ou corpo de requisição completo.
Exclusão por lista de campos permitidos é a primeira defesa; redaction é complementar.
Princípios de coleta segura: [OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

Mudanças críticas e revogações devem persistir seu evento na transação que altera
estado. Falha de auditoria durável aborta a mutação/execução crítica; falha ao enviar
notificação depois do commit não reverte a revogação. Para operação externa futura,
registrar intenção antes, resultado depois e incerteza se não houver confirmação.
Isso não torna PostgreSQL inviolável a administradores: separar privilégios de leitura,
escrita e retenção; exportação com proteção contra alteração precisa de projeto futuro.

Falhas anônimas em massa podem ser agregadas com contagens para não causar DoS por
logs; não omitir revogação, reuse reconhecido, recuperação ou ação crítica.
Notificações de segurança informam evento, horário e orientação de contenção sem
segredos. Retenção/acesso/expurgo de auditoria, backups e sinais de risco precisam de
aprovação antes de coletar dados reais; não reter indefinidamente por conveniência.

## 15. Critérios de aceitação para implementação futura

Estes são cenários exigidos, não testes executados na Fase 2A:

- Matriz de estados da conta, ausência de enumeração e negação segura quando o banco falha.
- Senha com salt distinto, Unicode/limites, rehash e custo limitado fora do event loop.
- Token de propósito/usuário/endereço errado, expirado ou usado não produz transição.
- Consumo concorrente de código, refresh, recovery code e aprovação tem um único vencedor.
- Access token opaco válido falha após revogação, reset e mudança de versão.
- Refresh concorrente/repetido e resposta perdida seguem a política estrita e registram reuse.
- Logout atual funciona sem prova recente; revogar recurso de outra conta sempre falha.
- Recuperação não emite sessão normal, não reativa `disabled` e aplica restrições/revogação.
- Relógio do cliente, refresh e flag biométrica não renovam autenticação recente.
- Gate desconhecido/negado não executa; step-up não altera ownership; parâmetros novos invalidam aprovação.
- Ordem entre revogação e execução crítica é testada com PostgreSQL real.
- Cookies/CSRF, XSS e isolamento de tokens são testados antes de habilitar cliente web.
- Auditoria não contém segredos nem interpreta entrada como log; falhas duráveis negam ação crítica.

## 16. Questões abertas e limites de aprovação

| Questão | Condição antes de implementação/ativação |
| --- | --- |
| Bibliotecas Argon2id, HMAC para código humano e parâmetros finais | Selecionar versões auditadas, benchmark e operação/rotação do pepper; nenhum pacote foi adicionado. |
| Passkeys/WebAuthn ou outro autenticador resistente a phishing e poderes remotos | ADR de autenticadores/consentimento e protocolo; manter ações de alto risco negadas até lá. |
| Recuperação sem e-mail e contestação | Definir provas independentes, transferência de endereço e atendimento sem bypass. |
| TTLs, limites e janela restrita de 24 h | Validar usabilidade/abuso/carga; alterar política central com justificativa registrada. |
| Provedor de e-mail e entrega | Avaliar proteção de dados, falhas, templates e origem dos links; nenhuma integração nesta fase. |
| Cliente web/mobile e confiança local | Escolher topologia de cookies e estratégia de armazenamento/verificação antes de habilitar cada cliente. |
| Retenção e acesso a eventos/backups | Aprovar finalidade, prazos, controles e testes de restauração antes de dados reais. |
| E-mail internacional e endereços sensíveis a caixa | Revisar suporte e migração da chave de comparação antes de ampliar a política inicial. |

Os ADRs aprovam o desenho, não certificam sua segurança em execução. Nenhuma das
garantias futuras substitui a validação de implementação, integração e abuso.
