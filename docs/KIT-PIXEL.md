# Kit Pixel Art (v0.6)

Ferramentas determinísticas (Pillow + NumPy) para sprites. Elas não dependem do modelo, então funcionam do mesmo jeito com modelos de 0,5B ou de 70B. O modelo só escolhe a operação quando você pede pelo chat.

## Instalar e ativar
```powershell
.\instalar.ps1 -ComPixel        # ou: pip install -e ".[pixel]"
nlr kits --ativar pixel         # ou a aba 🧰 Kits na interface
```
Com o kit **desligado**, os comandos `nlr pixel …` e a aba Kits continuam funcionando, mas o agente não vê as ferramentas `pixel_*`. Isso mantém o prompt curto para modelos pequenos.

## Comandos
| Comando | Exemplo |
|---|---|
| Redimensionar (nearest, sem borrar) | `nlr pixel redimensionar heroi.png --largura 32` (128→32) |
| Ampliar inteiro | `nlr pixel upscale heroi_32.png --fator 8` |
| Paletas | `nlr pixel paletas` · `nlr pixel paleta aplicar heroi.png --paleta pico-8 [--dither]` · `paleta reduzir --cores 8` · `paleta extrair -o minha.gpl` |
| Remover fundo | `nlr pixel fundo heroi.png` (cor do canto; `--cor "#00ff00" --tolerancia 10`) |
| Prévia/GIF | `nlr pixel preview heroi.png` · `nlr pixel gif q1.png q2.png q3.png --duracao 120 --fator 4` |
| Spritesheet | `nlr pixel sheet montar q*.png --colunas 4` (gera PNG + JSON no formato hash do Aseprite) · `nlr pixel sheet fatiar sheet.png --largura 16 --altura 16` |
| Referências/tutoriais | `nlr pixel referencias "animação de corrida 16x16"` (pesquisa web) |

As paletas embutidas são `pico-8`, `db16`, `db32`, `endesga-32`, `gameboy` e `1bit`. Também aceita arquivos `.gpl` (GIMP/Aseprite), `.hex` (Lospec) e `.pal` (JASC), ou uma lista `"#000000,#ffffff"`. A cor mais próxima é escolhida em espaço **CIELAB** (perceptual).

## Aseprite
A detecção segue esta ordem: `kits.pixel.aseprite` no `config.yaml`, depois a variável `ASEPRITE`, depois o `PATH`, e por fim locais comuns (`C:\Program Files\Aseprite\Aseprite.exe`, Steam `steamapps\common\Aseprite`, itch, `%LOCALAPPDATA%\Programs`, macOS e Linux). Para conferir, rode `nlr pixel aseprite info`.

```powershell
nlr pixel aseprite exportar heroi.aseprite -o saida\heroi.png --escala 4     # quadro a quadro: heroi{frame}.png
nlr pixel aseprite sheet heroi.aseprite -o saida\heroi-sheet.png --tipo packed  # + heroi-sheet.json (json-hash, tags)
nlr pixel aseprite scripts-lua                                                # salva aplicar_paleta.lua, exportar_camadas.lua, redimensionar.lua
nlr pixel aseprite script scripts_aseprite\aplicar_paleta.lua --arquivo heroi.aseprite --param paleta=db32.gpl --param saida=heroi-db32.aseprite
```
Tudo roda em `aseprite --batch …`. Pelo agente, executar o Aseprite passa pela política de comandos e pede confirmação.

**Sem Aseprite instalado**, `exportar` e `sheet` usam um **leitor .aseprite embutido**. Ele lê camadas visíveis em modo normal, opacidade, cels RGBA/tons de cinza/indexado (compressão zlib), cels vinculados, durações e tags. Ele não lê modos de mesclagem, tilemaps, grupos aninhados com opacidade, slices nem camadas de referência. Para esses casos, use o Aseprite real.

## Pelo chat (kit ativo)
> "Reduza sprites/heroi.png para 32 px com a paleta DB32 e gere uma prévia"

O agente usa `pixel_imagem` (com `operacao=redimensionar`, depois `aplicar_paleta`, depois `preview`). Também há `pixel_spritesheet`, `pixel_aseprite` e `pixel_referencias`.

## Limitações
- Não é editor de desenho: não desenha sprites do zero nem anima.
- A revisão por modelo de visão ainda não existe (está no roteiro).
- A integração com o Aseprite real **não foi testada** neste ambiente. Os testes usam um executável falso que confere os argumentos.
