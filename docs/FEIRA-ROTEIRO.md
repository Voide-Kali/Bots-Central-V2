# Roteiro da demonstracao (feira)

Guia pratico para apresentar o Aval ao vivo, com o que falar, o caminho exato de cliques, as
perguntas provaveis dos avaliadores e o plano B. Companheiro do
[FEIRA-TOUR-CODIGO.md](FEIRA-TOUR-CODIGO.md), que explica o codigo.

## O pitch (30 segundos)

> "O Aval e uma central para gerenciar os meus proprios computadores pelo celular. A pergunta de
> pesquisa e: **como deixar uma IA agir sobre computadores sem poder ser manipulada?** A resposta
> do Aval e simples: a IA consulta e *propoe*, mas nada perigoso acontece sem a minha aprovacao.
> Toda acao e um comando de um catalogo fechado, aprovado por um segundo fator, e tudo fica
> registrado. O nome vem dai: nada age sem o meu **aval**."

## Antes de comecar (checklist)

- [ ] Servidor (tropa) ligado, online no Tailscale, stack de pe (`docker compose ps`).
- [ ] Um computador ja pareado e **online** (o proprio tropa ou o Mac).
- [ ] Telegram aberto no celular, conta ja vinculada, com PIN de acao definido.
- [ ] Painel aberto em `https://aval.tail5e5757.ts.net/` num navegador, deslogado (para mostrar o login).
- [ ] **Video de backup** gravado da demo completa, caso a rede/energia falhe (ver Plano B).
- [ ] Modo Feira pronto como tela de espera.

## Roteiro passo a passo

Cada passo tem o **que fazer** e uma **fala** sugerida.

### 1. A pagina inicial
- Abrir `https://aval.tail5e5757.ts.net/`.
- Fala: "Essa e a porta de entrada. O sistema inteiro mora num servidor em casa, sem nenhuma porta
  aberta na internet: o acesso e so pela rede privada Tailscale, com HTTPS."

### 2. Criar conta (mostra o cuidado com senha)
- Ir em "Criar conta". Digitar o e-mail e comecar a digitar a senha devagar.
- Fala: "Repare na barra de forca: ela guia o usuario a uma frase-senha longa. A politica pede 15
  caracteres, no estilo do NIST: comprimento vale mais que simbolos. A senha e guardada com
  Argon2id, nunca em texto."
- (Se preferir nao criar conta ao vivo, entrar com uma conta ja criada.)

### 3. O painel e um computador
- Entrar no painel (`/painel/`). Mostrar a lista de computadores e a telemetria.
- Fala: "Aqui vejo presenca e telemetria ao vivo: CPU, memoria, disco, temperatura. Cada
  computador roda um agente em Go que manda um heartbeat **assinado** a cada poucos segundos."

### 4. Identidade e aprovacao de um computador (se der tempo)
- Mostrar o fluxo de "Adicionar computador": o painel monta o comando de instalacao.
- Fala: "Quando um computador novo se apresenta, ele gera uma chave propria e eu aprovo pelo
  **fingerprint**. Sem a minha aprovacao, ele nao entra."

### 5. Renomear e organizar
- Clicar num computador, usar **Renomear** (ex.: "Servidor da sala").
- Fala: "Posso dar nomes que eu entenda. E, se quiser, **Remover** um computador tira ele do painel."

### 6. O coracao: uma acao com aval
- Propor uma acao de baixo risco pelo painel ou pelo Telegram (ex.: `lock_screen` ou `webcam_photo`).
- No celular, chega o pedido; **digitar o PIN de 6 digitos** para aprovar.
- A acao executa; o resultado volta.
- Fala: "Esse e o ponto central. A acao so existe como um comando de um **catalogo fechado** - nao
  ha execucao de shell livre. Para acontecer, eu aprovo com um **segundo fator**: o PIN no Telegram.
  O backend assina um resumo do comando e o agente so executa se bater."

### 7. A IA que propoe, mas nao age
- Perguntar algo a IA pelo Telegram (ex.: "qual computador esta mais quente?").
- Fala: "A IA roda **localmente** no servidor, com Ollama. Ela so **le** e **propoe** - nao tem
  ferramentas, nao tem credenciais, e trata o conteudo externo como dado, nunca como ordem. Mesmo
  que alguem tente enganar a IA, ela nao consegue executar nada sozinha."

### 8. Tudo fica registrado
- Abrir a aba **Historico**.
- Fala: "Cada acao vira uma linha de auditoria - quem, o que, quando, resultado. E uma tabela
  **append-only**: um gatilho no banco recusa alteracao e exclusao. Nem o proprio sistema reescreve
  o historico."

### 9. Fecho
- Fala: "Resumindo a pesquisa: a IA e util, mas o poder de agir fica sempre com a pessoa, em
  camadas - catalogo fechado, aprovacao por segundo fator, assinatura, auditoria. Esse e o aval."

## Perguntas provaveis dos avaliadores

- **"E se a IA for enganada (prompt injection)?"** A IA nao tem ferramentas nem credenciais e so
  propoe. O conteudo que ela le e tratado como dado. Mesmo enganada, ela nao alcanca os agentes nem
  executa acoes; o maximo e sugerir um comando, que ainda depende da minha aprovacao por PIN.
- **"E se o servidor for invadido?"** Reduzi o estrago: o app conecta ao banco com um papel de
  **menor privilegio** (nao e dono, nao mexe no schema nem na auditoria), a senha do dono do banco
  nao fica no ambiente dos processos expostos, os backups sao cifrados, e nao ha portas abertas na
  internet. A protecao mais forte - aprovacao assinada no celular e verificada pelo agente - esta no
  roadmap; e honesto dizer que, hoje, confio no servidor para a assinatura das acoes.
- **"Quanto custa?"** Zero: servidor proprio, Ubuntu, Docker, PostgreSQL, Ollama, Tailscale e
  Telegram no plano gratuito.
- **"E privacidade/LGPD?"** Tem Politica de Privacidade e Termos. A IA de e-mail (que leria caixas)
  foi **tirada** do Aval de proposito e vive num projeto separado; o Aval nao le e-mail de ninguem.
- **"Usou IA para construir?"** Sim, e declaro. Uso IA como ferramenta de arquitetura e
  implementacao, mas entendo e sei explicar cada parte (ver o tour do codigo). O merge e sempre meu,
  nenhuma IA aprova o proprio trabalho, e segredos nunca entram em nenhuma IA.

## Plano B (se algo falhar)

- **Rede/energia cai:** passar o **video de backup** da demo completa.
- **Um computador ficou offline:** usar o outro, ou mostrar pelo Modo Feira e explicar o fluxo.
- **IA local lenta:** ela e opcional na demonstracao; o nucleo (acao com aval) nao depende dela.
- **Telegram sem sinal:** mostrar a aprovacao por **codigo de e-mail** como alternativa ao PIN.

## Materiais que ainda faltam (fora deste roteiro)

- Banner e relatorio (ABNT, se o evento pedir).
- Gravar o video de backup seguindo este roteiro.
