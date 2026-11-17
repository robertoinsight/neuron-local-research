# Segurança

O agente pode ler e escrever arquivos e rodar comandos. Por isso ele vem **travado por padrão** e você libera aos poucos.

## Resumo das regras (padrão)

| Ação | Regra padrão |
|---|---|
| Escrever, editar ou criar arquivos | **Só dentro da área de trabalho** (a pasta do projeto em `projetos/<id>/`, ou `dados/area_de_trabalho/` no chat). Caminhos fora dela, `..` e links que saem dela são recusados. |
| Apagar | Só dentro da área de trabalho, nunca a própria raiz dela; nunca a pasta interna `.agente/` (só `.agente/tmp`). |
| Ler arquivos | Área de trabalho + pastas da biblioteca + `seguranca.pastas_extra_leitura`. |
| Rodar comandos | **Pede confirmação** (`Autorizar? [y/N]`, padrão **Não**) para *todo* comando. Sem terminal interativo, a resposta é **não**. |
| Modo autônomo | Desligado. Quando ligado (`--autonomo` numa execução, ou `seguranca.modo_autonomo: true`), só os comandos da lista `comandos_permitidos` rodam sem perguntar — e só se não encadearem/redirecionarem (`;`, `&&`, `|`, `>`, `` ` ``, `$(`, `%VAR%`). O resto continua pedindo confirmação. |
| Comandos perigosos | **Sempre bloqueados**, mesmo com confirmação ou modo autônomo (lista abaixo). |
| Tempo limite | `seguranca.timeout_comando` (120 s). Ao estourar, a árvore de processos é encerrada. |
| Saída de comandos | Truncada em `max_saida_comando` caracteres. |
| Variáveis de ambiente | Os comandos rodam **sem** variáveis cujo nome contém `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `SENHA`, `CREDENTIAL` ou `AUTH`. |
| Rede | Ferramentas de rede são só leitura (busca e GET de páginas, com `http/https` apenas). Não há ferramenta de envio, postagem ou upload. |
| Segredos | Ficam no `.env` (nunca no `config.yaml`). O `.env` não vai no zip/git. |
| Ferramentas MCP | Pedem confirmação a cada uso, a menos que o servidor esteja com `permissao: livre`. |
| Interface web | Não tem como perguntar "autorizar?" comando a comando; lá, comandos só rodam com a caixa "modo autônomo" marcada **e** se estiverem na lista. Os demais são negados. |

## Lista de bloqueio (sempre negados)

Remoção recursiva (`rm -r`, `rd /s`, `del /s /q`, `Remove-Item -Recurse`), `rm` com `/`, `~`, `*` ou `..`; formatação/partição (`format C:`, `mkfs`, `diskpart`, `fdisk`, `Format-Volume`, `Clear-Disk`); `dd if=`; desligar/reiniciar; alterações no registro do Windows; `bcdedit`, `vssadmin`, `takeown`, `icacls`…; `sudo`/`runas`; "baixar e executar" (`curl … | sh`, `irm … | iex`, `Invoke-Expression`); `Set-ExecutionPolicy`; `chmod 777 /…`; *fork bomb*; `git push`, `git reset --hard`, `git clean -f`; gerenciamento de usuários; agendamento de tarefas (`schtasks`, `crontab`); conexões remotas (`ssh`, `scp`, `ftp`, `nc`…); qualquer menção a pastas do sistema (`/etc/`, `/usr/`, `C:\Windows`…); escrita direta em dispositivos.

Você pode **acrescentar** expressões regulares em `seguranca.comandos_bloqueados`. Não é possível remover as embutidas pela configuração (de propósito).

## Configuração

```yaml
seguranca:
  modo_autonomo: false          # true = comandos da lista rodam sem perguntar
  comandos_permitidos: [python, python3, py, pytest, "python -m pytest", "pip list", "pip show", node,
                        "npm test", "npm run", "git status", "git diff", "git log", "git init", "git add",
                        "git commit", ls, dir, echo]
  comandos_bloqueados: []       # regex extras
  timeout_comando: 120
  max_saida_comando: 8000
  pastas_extra_leitura: []      # pastas fora da biblioteca que o agente pode LER
  execucao: local               # local | docker
  imagem_docker: python:3.12-slim
```

## Limites honestos (leia!)

- **Liberar `python` (ou `node`) na lista equivale a liberar qualquer código.** Um script Python pode, em tese, apagar arquivos fora da área de trabalho — a política vale para as *ferramentas* do agente e para o texto do comando, não para o que o programa faz depois de iniciado. Se for usar o modo autônomo com projetos de código, prefira `execucao: docker` (o comando roda num contêiner com só a pasta do projeto montada e **sem rede**: `--network none`) ou rode o agente numa conta de usuário/VM separada.
- A lista de bloqueio é por padrões de texto: ajuda muito contra acidentes do modelo, mas não é uma *sandbox*. Um comando ofuscado de propósito pode escapar — por isso o padrão é pedir confirmação.
- Conteúdo de páginas da web e de documentos pode conter "instruções" maliciosas (*prompt injection*). O agente trata esse conteúdo como dados, mas um modelo pequeno pode se confundir: é mais um motivo para manter a confirmação ligada.
- No Windows, `execucao: docker` exige o Docker Desktop (com WSL2).

## Recomendações

1. Comece sem modo autônomo e observe o que o agente pede para rodar.
2. Use `--autonomo` só por execução (`nlr projeto novo "..." --autonomo`), não no `config.yaml`.
3. Para projetos de código desconhecidos, use `execucao: docker`.
4. Não coloque pastas de sistema ou com segredos em `pastas_extra_leitura` nem na biblioteca.
5. Versione os projetos com `git` (o agente pode rodar `git init/add/commit`; `git push` é bloqueado).
