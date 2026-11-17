# Usar o Neuron Local Research com o LM Studio (passo a passo simples)

O NLR **não roda dentro da janela do LM Studio**. O LM Studio é o "motor" (ele roda o modelo) e o NLR conversa
com ele pelo servidor local `http://localhost:1234`. Você usa o NLR no terminal (`iniciar.bat chat`) ou no navegador
(`iniciar.bat`).

## Parte 1 — no LM Studio (uma vez)

1. Abra o LM Studio.
2. Baixe um modelo de chat (aba de busca/Discover). Para GPU de 8 GB: um modelo de 4 a 9B em **Q4_K_M**
   (ex.: Gemma 4 E4B, Qwen 3.5 9B). Para a biblioteca, baixe também um modelo de **embeddings**
   (ex.: `nomic-embed-text-v1.5`).
3. **Carregue** o modelo de chat (botão de carregar no topo). Em **Context Length**, use 8192 (ou mais se couber).
4. Vá na aba **Developer** e clique em **Start Server**. Deve aparecer **Status: Running** e a porta **1234**.

## Parte 2 — instalar o NLR (uma vez)

1. Descompacte `neuron-local-research-v0.3.zip` em uma pasta **sem espaços nem acentos**, ex.: `C:\IA\neuron-local-research`.
2. Dê **dois cliques** em `instalar.bat`.
   - Ele pergunta o idioma (1 = Português, 2 = English).
   - Baixa sozinho o `uv` e um Python 3.12 só para o NLR (não precisa instalar Python antes).
   - Como o servidor do LM Studio está ligado, ele percebe sozinho que você usa o LM Studio.
   - No fim, mostra o diagnóstico (`doctor`).

## Parte 3 — conferir

Abra o PowerShell na pasta do NLR (na pasta, clique na barra de endereço, digite `powershell` e Enter) e rode:

```
.\iniciar.bat modelos
```

Você deve ver a lista de modelos, com **sim** na coluna "carregado" e uma seta `←` no modelo que o NLR vai usar,
além do contexto real e do perfil (pequeno / médio / grande).

- Se aparecer "Nenhum modelo de chat estava carregado; escolhi ...": tudo bem, o LM Studio vai carregar esse modelo
  sozinho. Se preferir outro, carregue-o no LM Studio ou fixe o nome no `config.yaml`:
  `modelo_chat: "nome-exato-que-aparece-em-nlr-modelos"`.

## Parte 4 — usar

| Quero... | Comando |
|---|---|
| conversar no terminal | `.\iniciar.bat chat` |
| abrir no navegador | `.\iniciar.bat` (abre http://127.0.0.1:7860) |
| usar em inglês | `.\iniciar.bat --idioma en chat` |
| adicionar meus documentos | `.\iniciar.bat biblioteca adicionar "C:\Users\SeuNome\Documents\Biblioteca"` e depois `.\iniciar.bat indexar` |
| perguntar aos documentos | `.\iniciar.bat perguntar "o que diz o contrato sobre multa?" --modo biblioteca` |
| pesquisar na internet | `.\iniciar.bat pesquisar "melhores técnicas de pixel art 2026" --fontes web` |
| criar um projeto | `.\iniciar.bat projeto novo "crie um gerador de paletas em Python" --nome paletas` |

Dentro do chat: `/web`, `/biblioteca`, `/agente`, `/projeto`, `/nova`, `/sair`.

Quando a conversa ficar longa (perto de 80% do contexto), o NLR avisa
"O chat chegou a X% do contexto... continuei num chat novo" e segue normalmente, lembrando do que foi falado.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| "Não consegui conectar ao servidor de modelos 'lmstudio'" | No LM Studio, aba Developer, clique em Start Server. |
| "não há nenhum modelo de chat disponível" | Baixe um modelo de chat no LM Studio. |
| "O modelo 'x' não existe no servidor" | Copie o nome exato de `.\iniciar.bat modelos` para o `config.yaml`. |
| Respostas cortadas / erro de contexto | Recarregue o modelo com Context Length maior (8192 ou 16384). |
| Muito lento | Use um modelo menor ou com quantização Q4; feche outros programas que usam a GPU. |
| "GPU NVIDIA não detectada" | Pode ignorar: quem usa a GPU é o LM Studio, não o NLR. |
