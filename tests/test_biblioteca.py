import shutil
import time

from nlr.biblioteca.busca import buscar
from nlr.biblioteca.carregadores import carregar_arquivo
from nlr.biblioteca.embeddings import criar_embedder
from nlr.biblioteca.fatiamento import fatiar_codigo, fatiar_texto
from nlr.biblioteca.indice import IndiceBiblioteca
from nlr.llm.cliente import ClienteLLM


def _indice(cfg):
    return IndiceBiblioteca(cfg, criar_embedder(cfg, ClienteLLM(cfg)))


def test_carregadores_todos_formatos(pasta_amostras):
    pdf = carregar_arquivo(pasta_amostras / "manual.pdf")
    assert [s.local for s in pdf] == ["p. 1", "p. 2"] and "32 minutos" in pdf[0].texto
    docx = "\n".join(s.texto for s in carregar_arquivo(pasta_amostras / "contrato.docx"))
    assert "2.300,00" in docx and "Maria Souza | " not in docx.replace("Locador | Maria Souza", "")
    assert "Locador | Maria Souza" in docx
    xlsx = carregar_arquivo(pasta_amostras / "estoque.xlsx")
    assert "planilha Estoque" in xlsx[0].local and "| parafuso sextavado | 1200 |" in xlsx[0].texto
    csv_ = carregar_arquivo(pasta_amostras / "vendas.csv")
    assert "teclado mecânico" in csv_[0].texto and csv_[0].texto.count("|") > 4
    txt = carregar_arquivo(pasta_amostras / "viagem.txt")[0].texto  # cp1252
    assert "São Francisco" in txt


def test_fatiamento_texto_e_codigo():
    partes = fatiar_texto("palavra " * 500, 300, 50)
    assert len(partes) > 3 and all(len(p) <= 300 for p in partes)
    codigo = "\n".join([f"def f{i}():\n" + "\n".join(f"    x{j} = {j}" for j in range(30)) + "\n" for i in range(4)])
    tr = fatiar_codigo(codigo, "m.py", tamanho=500)
    assert all(t.local.startswith("linhas ") for t in tr)
    assert tr[0].texto.startswith("# arquivo: m.py (linhas 1-")
    # cada função começa no início de um trecho (fatiamento por estrutura)
    inicios = [t.texto.split("\n", 1)[1].lstrip("\n") for t in tr]
    assert sum(1 for x in inicios if x.startswith("def f")) >= 3


def test_indexacao_incremental_e_busca_com_citacao(cfg, tmp_path, pasta_amostras):
    pasta = tmp_path / "bib"
    shutil.copytree(pasta_amostras, pasta)
    cfg.biblioteca.pastas = [str(pasta)]
    idx = _indice(cfg)
    r1 = idx.indexar()
    assert r1.novos == 7 and not r1.erros and r1.sem_vetor == 0
    st = idx.status()
    assert st["trechos"] == st["trechos_com_vetor"] > 0
    # sem mudança
    r2 = idx.indexar()
    assert r2.novos == 0 and r2.atualizados == 0 and r2.inalterados == 7
    # altera, apaga e cria
    time.sleep(0.05)
    (pasta / "notas.md").write_text("# Bolo de cenoura\nCobertura de chocolate meio amargo.", encoding="utf-8")
    (pasta / "viagem.txt").unlink()
    (pasta / "novo.md").write_text("Lista de compras: abacaxi e hortelã.", encoding="utf-8")
    r3 = idx.indexar()
    assert (r3.novos, r3.atualizados, r3.removidos) == (1, 1, 1)
    res = buscar(idx, "cobertura chocolate bolo")
    assert res and res[0].caminho.endswith("notas.md")
    assert not any("pão de queijo" in r.texto for r in res)
    res = buscar(idx, "autonomia da bateria do drone")
    assert res[0].caminho.endswith("manual.pdf") and res[0].local == "p. 1"
    assert res[0].rotulo == "manual.pdf (p. 1)"
    res = buscar(idx, "quantidade de arruela inox no deposito")
    assert res[0].caminho.endswith("estoque.xlsx") and "planilha Estoque" in res[0].local
    res = buscar(idx, "classe MotorFisica gravidade")
    assert res[0].caminho.endswith("motor.py") and res[0].local.startswith("linhas ")
    res = buscar(idx, "multa rescisão aluguel")
    assert res[0].caminho.endswith("contrato.docx")


def test_sem_embeddings_usa_so_bm25_e_completa_depois(cfg, srv, tmp_path, pasta_amostras):
    cfg.biblioteca.pastas = [str(pasta_amostras)]
    srv.falhar_embeddings = True
    idx = _indice(cfg)
    r = idx.indexar()
    assert r.aviso_embeddings and r.sem_vetor > 0
    assert buscar(idx, "polvilho queijo")[0].caminho.endswith("notas.md")  # BM25 funciona
    srv.falhar_embeddings = False
    n = idx.completar_vetores()
    assert n > 0 and idx.status()["trechos_com_vetor"] == idx.status()["trechos"]


def test_modo_sem_embeddings_configurado(cfg, pasta_amostras):
    cfg.biblioteca.embeddings = "nenhum"
    idx = IndiceBiblioteca(cfg, criar_embedder(cfg, ClienteLLM(cfg)))
    r = idx.indexar()
    assert r.sem_vetor == 0 and not r.aviso_embeddings
    assert buscar(idx, "Ouro Preto pousada")[0].caminho.endswith("viagem.txt")


def test_ignora_pastas_e_arquivo_com_erro(cfg, tmp_path):
    pasta = tmp_path / "b2"
    (pasta / "node_modules").mkdir(parents=True)
    (pasta / "node_modules" / "lixo.js").write_text("function x(){}")
    (pasta / "quebrado.pdf").write_bytes(b"isto nao e um pdf")
    (pasta / "ok.md").write_text("conteudo valido sobre astronomia")
    cfg.biblioteca.pastas = [str(pasta)]
    idx = _indice(cfg)
    r = idx.indexar()
    assert r.novos == 1 and len(r.erros) == 1 and "quebrado.pdf" in r.erros[0][0]
    assert idx.status()["arquivos_com_erro"] == 1
