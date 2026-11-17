# Instalador .exe (Windows)

- `NLR.iss` — script do Inno Setup 6 (instala sem administrador em `%LOCALAPPDATA%\Programs\NLR`,
  cria atalhos no Menu Iniciar e, se quiser, na Área de Trabalho, e registra o desinstalador).
- `primeira-execucao.ps1` — roda no fim da instalação: baixa um Python 3.12 próprio com o `uv`, instala as
  dependências e cria `%APPDATA%\NLR\config.yaml` (detecta LM Studio ou Ollama).
- `NLR.cmd` — o atalho: abre a interface no navegador (http://127.0.0.1:7860).
- `nlr.ico` — ícone.

Como gerar o .exe:
1. **Automático (recomendado):** suba o projeto no GitHub e rode o workflow *instalador-windows*
   (aba Actions → Run workflow) ou crie uma tag `v0.4.0`. O .exe aparece em *Artifacts*/Release.
2. **No seu Windows:** instale o Inno Setup 6, baixe o `uv.exe` para `instalador\uv\uv.exe` e rode
   `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" instalador\NLR.iss`. O resultado fica em `instalador\saida\`.

O caminho de 1 clique sem .exe continua: `instalar.bat` e `iniciar.bat`.
