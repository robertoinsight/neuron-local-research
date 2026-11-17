# Kit ABNT (v0.6)

O kit gera referências **NBR 6023:2018**, citações autor-data **NBR 10520** (padrão 2023, com opção 2002) e documentos `.docx` no padrão **NBR 14724**. A formatação é feita por código, sem o modelo, então o resultado é igual com qualquer modelo.

> ⚠ **Revise sempre.** Os metadados vêm de Crossref, OpenLibrary, Google Books e das páginas, e podem estar incompletos. O que faltar aparece como `[S. l.]`, `[s. n.]` ou `[20--]` e gera um **aviso**. Normas e manuais de cada instituição podem pedir ajustes.

## Instalar e ativar
```powershell
.\instalar.ps1 -ComABNT        # ou: pip install -e ".[abnt]"  (python-docx)
nlr kits --ativar abnt
```
No `config.yaml`, em `kits.abnt`, ficam `autor`, `instituicao`, `curso`, `local`, `fonte` (Times New Roman ou Arial), `norma_citacao` ("2023" gera (Silva, 2020); "2002" gera (SILVA, 2020)) e `buscar_online`.

## Referências e citações
```powershell
nlr abnt ref 10.1038/nature14539 9788535914849 https://pt.wikipedia.org/wiki/Pixel_art
nlr abnt citar 10.1038/nature14539 --pagina 437      # (LeCun; Bengio; Hinton, 2015, p. 437)
nlr abnt arquivo biblioteca\artigo.pdf               # acha DOI/ISBN no texto; senão usa metadados do arquivo
```
- **DOI:** usa a Crossref (artigos, livros e capítulos).
- **ISBN:** consulta a OpenLibrary e, se não achar, o Google Books. O ISBN é validado pelo dígito verificador.
- **URL:** lê as metatags `citation_*`, Dublin Core, Open Graph e JSON-LD, mais a data de acesso de hoje.
- Com mais de 3 autores, a referência usa o primeiro seguido de *et al.*; sem autor, a entrada é pelo título (PRIMEIRA palavra em maiúsculas). Mesmo autor e mesmo ano viram 2020a/2020b. A lista sai em ordem alfabética.

## Documento NBR 14724
```powershell
nlr abnt documento texto.md --titulo "Pixel art em jogos independentes" --autor "Roberto ..." --ref 10.1038/nature14539 --ref 9788535914849
```
O documento sai em A4 com margens de 3 cm (superior e esquerda) e 2 cm (inferior e direita), fonte 12, espaçamento 1,5 e recuo de 1,25 cm. Ele contém, em ordem:
- capa;
- folha de rosto (com a natureza do trabalho recuada 8 cm);
- resumo opcional;
- **sumário**;
- seções numeradas (`#` vira 1, `##` vira 1.1, `###` vira 1.1.1), com cada seção primária começando em nova página;
- citações longas com `>` (recuo de 4 cm, fonte 10, espaço simples);
- **REFERÊNCIAS**, centralizado e alinhado à esquerda, com espaço simples.

A numeração aparece no canto superior direito a partir da parte textual, contando desde a folha de rosto.

O sumário é um campo do Word. Ao abrir o arquivo, clique com o botão direito e escolha **Atualizar campo** (F9). Até lá, o documento mostra uma prévia estática do sumário.

## Pesquisa profunda em ABNT
```powershell
nlr pesquisar "impacto de paletas limitadas na legibilidade" --profunda --formatos md,abnt
```
Na interface, marque **.docx ABNT** no modo Pesquisa profunda. As citações `[n]` viram (Autor, ano), a seção de fontes vira **REFERÊNCIAS** (URLs pela página, arquivos da biblioteca por DOI/ISBN encontrado no texto) e a pergunta vira o título da capa.

## Limitações
- Não gera listas de ilustrações e tabelas, apêndices e anexos, abstract, ficha catalográfica nem errata.
- Os tipos de referência cobertos são livro, artigo, capítulo, site, trabalho acadêmico e relatório. Legislação, eventos e patentes ainda não.
- Os casos raros da norma (autor-entidade com subordinação, títulos que começam com artigo, etc.) usam regras simplificadas.
