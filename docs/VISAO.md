# Visão: analisar imagens e pesquisar a partir delas (v0.7)

O Neuron Local Research usa um **modelo de visão local** (rodando no LM Studio, Ollama ou llama.cpp) para descrever imagens com detalhes, ler texto, revisar pixel art e pesquisar na internet o que aparece na imagem. Tudo roda no seu PC. A imagem **só sai do computador** se você ligar a busca reversa opcional, explicada abaixo.

## 1. Escolher um modelo de visão (8 GB de VRAM)

No LM Studio, procure modelos com o **ícone de olho 👁 ("Vision")** na busca e na lista de modelos. Um modelo sem o olho **não enxerga imagens**, mesmo que aceite o arquivo.

| Modelo (LM Studio) | Quantização | VRAM aprox. | Observação |
|---|---|---|---|
| **Qwen2.5-VL 7B Instruct** | Q4_K_M | ~6 GB | Melhor equilíbrio. Recomendado para OCR, análise minuciosa e pesquisa |
| **Qwen3-VL 8B** (se aparecer no catálogo) | Q4_K_M | ~6–7 GB | Sucessor do 2.5-VL, costuma ser melhor |
| **Gemma 3 4B** | Q4_K_M | ~3,5 GB | Rápido, bom em descrição geral, mais fraco em OCR |
| **Gemma 3 12B** | Q4_K_M | ~8–9 GB | Melhor qualidade, mas parte vai para a RAM (mais lento) |
| **MiniCPM-V 2.6** | Q4_K_M | ~5 GB | Bom em OCR e documentos |
| Qwen2.5-VL 3B | Q4_K_M | ~2,5 GB | Funciona até em CPU. É o que foi testado aqui (resultados na seção 7) |

Os modelos de visão no formato GGUF vêm com um arquivo extra (`mmproj`). O LM Studio baixa os dois juntos.

## 2. Configurar

No `config.yaml`:

```yaml
modelo:
  modelo_visao: "qwen2.5-vl-7b-instruct"   # vazio = usa o modelo_chat, se ele tiver visão

visao:
  modo_padrao: minucioso    # minucioso | geral | texto | pixel
  lado_max: 1536            # lado máximo enviado ao modelo
  recortes: true            # minucioso: 4 quadrantes ampliados
  max_imagens: 4            # por mensagem
  links_manuais: true       # botões Google Lens / Bing / TinEye na interface
  busca_reversa:
    provedor: desligado     # desligado | serpapi
    consentimento_envio: false
```

Como o modelo de visão é escolhido:
1. Usa o `modelo_visao`, se estiver preenchido.
2. Se não estiver, usa o `modelo_chat`, caso ele tenha visão (ex.: Qwen2.5-VL ou Gemma 3 como modelo único).
3. Se o chat não tiver visão, usa um modelo de visão **já carregado** no servidor.

O programa confere isso no LM Studio (`/api/v0/models`, tipo `vlm`), no Ollama (`capabilities: vision`) e no llama.cpp (`/props`). Se o modelo escolhido não tiver visão ou não estiver carregado, aparece um aviso com a correção. Para ver o estado:

```
nlr imagem status
```

## 3. Usar

**Interface (`nlr ui`)**
- Anexe a imagem pelo 📎 → **🖼 Imagem**, arraste para o chat ou cole com **Ctrl+V** (print da tela, por exemplo).
- A miniatura aparece acima da caixa de texto, junto com as ações rápidas:
  - **Analisar minuciosamente**
  - **Ler texto**
  - **Revisar pixel art**
  - **Pesquisar na internet pela imagem**
- Se você só escrever uma pergunta e enviar, o programa escolhe o modo pela pergunta.
- O botão 🔎 abre a **busca reversa manual**: a imagem é copiada para a área de transferência e o Google Lens, o Bing Visual Search ou o TinEye abre numa aba nova. Lá, você cola a imagem com Ctrl+V.
- A interface antiga em Gradio (`nlr ui --gradio`) também tem uma aba **Imagem**.

**Terminal**

```
nlr imagem analisar foto.jpg                         # minucioso (padrão)
nlr imagem analisar print.png --modo texto           # transcreve o texto (OCR)
nlr imagem analisar sprite.png --modo pixel          # revisão de pixel art
nlr imagem analisar foto.jpg -m geral -p "Que planta é essa?"
nlr imagem pesquisar foto.jpg --foco "onde comprar"  # identifica + pesquisa na web, com fontes
nlr imagem analisar foto.jpg --salvar analise.md
nlr --idioma en imagem analisar --help               # ajuda em inglês
```

No chat (`nlr chat`), o agente também usa sozinho as ferramentas `analisar_imagem` e `pesquisar_por_imagem` quando você cita o caminho de uma imagem.

## 4. Como funciona

- **Minucioso, em etapas:** modelos locais reduzem a imagem e perdem detalhes. Por isso o programa:
  1. divide a imagem em 4 quadrantes ampliados;
  2. pede ao modelo notas curtas de cada quadrante;
  3. faz uma chamada final com a imagem inteira e as notas, que gera a análise estruturada (visão geral, elementos, texto, detalhes, dúvidas).
- **Texto:** transcrição fiel, preservando linhas e valores.
- **Pixel art:** o Pillow mede objetivamente a imagem (número de cores, pixels isolados, pixels semitransparentes, tamanho) e essas medidas vão para o modelo. O modelo também é instruído a não sugerir antialiasing automático. Sprites pequenos são detectados e ampliados sem suavizar.
- **Pesquisar pela imagem:**
  1. O modelo de visão preenche um plano em JSON: descrição, texto visível, se há pessoas e até 3 buscas.
  2. O programa faz essas buscas na web.
  3. A resposta é escrita com fontes numeradas [n].
  4. Se o modelo não devolver JSON, há um plano alternativo.
- **Repetições:** modelos pequenos às vezes entram em loop. O programa usa penalidade de repetição e remove linhas repetidas.
- **EXIF:** câmera, data e software entram no contexto. As coordenadas de GPS **não** são enviadas; o programa só informa se a foto tem GPS.

## 5. Busca reversa (encontrar a mesma imagem na internet)

Por padrão, a pesquisa usa só a **descrição** da imagem, sem enviar a foto. Isso preserva a privacidade, mas não encontra cópias exatas, como o Google Lens faz.

Duas opções para busca reversa de verdade:

1. **Manual, sem chave e sem custo.** Na interface, use o botão 🔎 → Google Lens, Bing ou TinEye. Você mesmo cola a imagem no site.
2. **Automática, pela SerpApi (API oficial do Google Lens, paga, com plano gratuito limitado).** Para ligar:
   - crie uma conta em serpapi.com;
   - coloque `SERPAPI_API_KEY=...` no `.env`;
   - no `config.yaml`, use `provedor: serpapi` e `consentimento_envio: true`.

   A imagem vai **reduzida e sem EXIF** para os servidores da SerpApi. Os resultados entram como fontes.

Não existe hoje uma forma gratuita, confiável e permitida pelos termos de uso de fazer busca reversa automática sem chave. Raspar o Google Lens, o Bing ou o TinEye viola os termos e quebra com frequência. O SearXNG não aceita busca por upload de imagem.

**Pessoas:** o programa **não faz reconhecimento facial** nem tenta identificar quem é uma pessoa. O modelo é instruído a descrever só aparência, roupas, cenário e ações, sem dar nomes. Se ele detectar pessoas na imagem, a busca reversa automática é bloqueada. (Um modelo pequeno pode, raramente, desobedecer a instrução: não use a ferramenta para identificar pessoas.)

## 6. API

Veja `docs/API.md`. As rotas são `POST /api/imagens`, `GET /api/imagens/{id}`, `GET /api/visao`, `POST /api/imagem/analisar` e `POST /api/imagem/pesquisar`.

## 7. Resultados reais e limitações (teste honesto)

Teste feito em Linux, **só na CPU** (8 threads), com **Qwen2.5-VL 3B Q4_K_M** no llama.cpp. Um modelo de 7B numa GPU de 8 GB deve ser bem melhor e mais rápido.

| Tarefa | Tempo | Qualidade |
|---|---|---|
| Ler texto de print de erro (modo texto) | 5–13 s | Ótima: transcrição perfeita, inclusive o valor em R$ |
| Torre Eiffel (minucioso) | ~113 s | Identificou corretamente. A estrutura saiu boa, mas os detalhes por região ficaram rasos |
| Gato (minucioso) | ~80 s | Razoável, com alguns itens vagos |
| Girassol (geral) | ~39 s | Boa |
| Revisão de sprite (pixel) | 33–46 s | Fraca: usou as medidas, mas as sugestões foram genéricas |
| Pesquisar pela imagem (Torre Eiffel) | ~55 s | Boa: buscas certas, fontes da Wikipédia e a altura com citação [n] |
| Pesquisar pela imagem (print de erro) | ~77 s | Útil, mas repetitiva e quase sem citações |

Limitações:
- A revisão de pixel art precisa de um modelo de 7B ou maior para dar críticas confiáveis.
- O modo minucioso faz 5 chamadas ao modelo, então é bem mais lento que o geral.
- Ainda não foi testado no Windows, com o LM Studio de verdade, em GPU, com modelos de 7B ou mais, nem com a SerpApi real (só com simulações).
