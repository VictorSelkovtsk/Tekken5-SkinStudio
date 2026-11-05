# Tekken 5 Skin Studio

Ferramenta para trocar e importar roupas no **Tekken 5 de PS2 (USA 1.00, SLUS-21059)**.

Autor: **VictorSelkovtsk** · Licença: **GPL-3.0**

*English: a local tool to swap and import costumes into Tekken 5 (PS2, USA 1.00). The interface is available in English, Portuguese and Spanish (top right corner).*

## Download e uso

1. Baixe o `Tekken5-SkinStudio-<versão>.zip` da página de releases e extraia numa pasta com espaço livre.
2. Abra o `Tekken5_SkinStudio.exe`.
3. Na **configuração inicial**, indique a sua ISO **original** do Tekken 5. A ferramenta confere se é a versão USA 1.00 e recusa outras. Para mudar depois, use *Arquivo › Pastas e jogo*.

O pacote já inclui o Blender 2.79 portátil, na pasta `runtime`. Não é preciso instalar mais nada.

Nenhum arquivo do jogo acompanha o programa. A ISO original nunca é alterada: os mods vão para uma **ISO nova**, gerada pelo Studio.

## Idiomas

A interface está em **português**, **inglês** e **espanhol**. Escolha no menu *Idioma (Language)* ou na configuração inicial; a troca vale na hora e fica salva.

Para acrescentar ou corrigir um idioma, crie a pasta `lang` ao lado do `Tekken5_SkinStudio.exe` e coloque nela um JSON no formato de `tools/skins_t5/lang/en.json`:
- `"_name"` é o nome do idioma;
- as chaves são os textos em português e os valores, a tradução;
- marcadores como `{0}` devem continuar no texto.

## Roupas originais do Tekken 5

No painel **Fontes**, a opção **Tekken 5** lista todas as roupas do jogo, por personagem.

- **Prévia:** modelo texturizado, com cores por osso, peso de cada osso e ossos de física.
- **Animações do jogo:** a aba **Animações** toca os golpes e movimentos do personagem, com play/pausa, linha do tempo, velocidade e loop. **Mover raiz** desloca o personagem pelo chão, como no jogo. As animações também funcionam na prévia de uma skin importada, porque ela usa o esqueleto da roupa base.
- **Trocar texturas:** na aba **Materiais**, dê duplo clique numa textura (ou use **Trocar textura…**) e escolha qualquer imagem. A prévia já mostra como fica no PS2: no tamanho original e reduzida à paleta da textura (16 ou 256 cores). **Original** desfaz a troca.
- **Salvar texturas como mod:** cria um mod que substitui só as texturas da roupa. Modelo, esqueleto e física continuam os originais, e o tamanho do pacote não muda.

## Importar uma roupa de outro jogo

1. Escolha uma fonte: **Tekken 4** (exports `scene.json`), **Tag HD** (`.kmd` da versão PS3) ou **XPS** (`.xps`, `.mesh`, `.mesh.ascii`, com as texturas ao lado do modelo).
2. Escolha o personagem de destino e a roupa base. A base fornece o esqueleto, as animações e os dados nativos do Tekken 5.
3. Escolha **Substituir roupa** ou **Criar novo slot**. O limite é de cinco roupas por personagem. Xiaoyu já tem cinco e só aceita substituição; Jinpachi e Eddy não recebem slots novos.
4. Em **Ossos e proporções**, confira escala, orientação, altura e a associação dos ossos. O **Teste de pesos** mostra a deformação de um osso e seus filhos.
5. Em **Materiais**, ative as partes desejadas, troque texturas e defina a cor padrão.
6. Dê um nome ao mod e clique em **Converter e adicionar aos mods**.
7. Ative os mods à direita e clique em **Gerar ISO com mods**. A ferramenta confere os recursos e o executável da ISO nova.

**Escolher o traje no jogo:** o esquema de botões muda com a quantidade de roupas.

| Roupas | 1P | 2P | 3P | 4P | 5P |
| --- | --- | --- | --- | --- | --- |
| 2 | Quadrado / Triângulo | X / Círculo | — | — | — |
| 3 | Quadrado | X / Círculo | Triângulo | — | — |
| 4 | Quadrado | X | Triângulo | Círculo | — |
| 5 | Quadrado | X | Start | Triângulo | Círculo |

## Editar no Blender 2.79

1. Com a skin carregada, abra a aba **Blender** e clique em **Editar no Blender**. A ferramenta cria um projeto na pasta `edits`, com malhas, texturas, UVs, esqueleto T5 e grupos de pesos.
2. Edite a malha, os UVs ou os pesos. Preserve os nomes, a hierarquia e a pose de repouso dos ossos.
3. Salve com **Ctrl+S** (ou **Salvar para o Studio**, na aba **T5 Skin Studio** do Blender).
4. Volte ao Studio, clique em **Recarregar edição**, confira a prévia e converta o mod.

No Blender, **Importar base original T5** traz a roupa original na camada 2, para reaproveitar partes dela na skin.

## Conferir ossos, caminhada e física

- **Visualização** (barra de ferramentas): troca a textura por **Cores por osso**, **Peso de um osso** ou **Física do jogo**.
- **Teste de pesos** (aba **Ossos e proporções**): gira um osso e seus filhos para conferir a deformação.
- Na aba **Ossos e proporções**, dê duplo clique numa linha para levar aquele osso da fonte para outro osso do Tekken 5.
- As animações do jogo mostram a skin em movimento antes de ir ao jogo. A física real (cabelo, tecidos) acontece só no jogo.

## Mods

- **Editar:** reabre a skin com tudo o que foi salvo no mod; **Salvar alterações no mod** a reconverte no mesmo lugar.
- **Excluir…:** move a pasta do mod para `mods/.lixeira`. Para recuperar, mova a pasta de volta para `mods` e abra o Studio de novo: o mod volta desligado.
- **Tirar uma skin do jogo:** desative o mod e gere outra ISO a partir da original. ISOs já geradas não mudam.
- Dois mods não podem substituir a mesma roupa ao mesmo tempo.

## Limites

- **Memória do PS2:** cada skin precisa caber em 1,55 MB, o tamanho da maior roupa original. As texturas são reduzidas automaticamente; se ainda não couber, a conversão informa quanto reduzir dos triângulos no Blender (Decimate).
- O formato de destino usa texturas de 256 cores. Normal maps, shaders PBR e a física do XPS não são transferidos.
- A física de cabelo e tecidos da fonte não é recriada: a skin usa a física da roupa base.
- Nas animações do jogo, os dedos e o rosto ficam na pose de repouso; o corpo é animado.
- Toda skin importada precisa ser testada no jogo.

## Código-fonte

Requisitos: Python 3.11 com PyQt5, NumPy e Pillow (`pip install -r requirements.txt`).

```powershell
python -m tools.skins_t5.qt
```

Para gerar o `.exe` (precisa do PyInstaller): `build_exe.bat`.

| Módulo | Função |
| --- | --- |
| `tools/skins_t5/qt/` | Interface (PyQt5). |
| `studio.py` | Operações do Studio: fontes, prévia, mods, ISO e Blender. |
| `sources.py`, `taghd.py` | Leitura das fontes (Tekken 4, Tag HD, XPS). |
| `convert.py`, `native.py` | Adaptação ao esqueleto e pacote nativo do Tekken 5. |
| `original.py`, `anim64.py` | Roupas originais, mods de textura e animações do jogo. |
| `game.py` | Catálogo de roupas, novos slots e geração da ISO. |
| `blender.py`, `blender279_edit.py` | Projeto do Blender 2.79 e retorno ao Studio. |
| `i18n.py`, `lang/` | Idiomas da interface. |

## Créditos

- O decodificador de animações comprimidas (formato 0x64) é uma adaptação para Python do `ParseAnimation0x64` do [TKMovesets](https://github.com/Kiloutre/TKMovesets), de Kiloutre (GPL-3.0). Por isso o Skin Studio também é distribuído sob a GPL-3.0.
- A leitura de XPS teve como referência o importador [XNALaraMesh](https://github.com/johnzero7/XNALaraMesh), de johnzero7.
- O pacote inclui o [Blender 2.79](https://www.blender.org) (GPL), sem modificações.

## Licença

[GPL-3.0](LICENSE) © 2026 VictorSelkovtsk.

Ferramenta de fãs, sem vínculo com a Bandai Namco. *Tekken* é marca da Bandai Namco Entertainment. Nenhum arquivo do jogo é distribuído com este programa.
