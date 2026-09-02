PYTHON ?= python3

.DEFAULT_GOAL := all

all: pdf site

pdf: formula.pdf competition.pdf

formula.pdf: formula.tex rules/2026/formula-technical/rules.tex template.tex
	latexmk -lualatex -interaction=nonstopmode -halt-on-error formula.tex

competition.pdf: competition.tex rules/2026/formula-competition/rules.tex template.tex
	latexmk -lualatex -interaction=nonstopmode -halt-on-error competition.tex

site: pdf
	$(PYTHON) build.py --skip-pdf

site-without-pdf:
	$(PYTHON) build.py --skip-pdf --allow-missing-pdf

check:
	$(PYTHON) -m unittest discover -s tests -v

check-web:
	npm run test:web

check-upstream:
	$(PYTHON) scripts/check_upstream.py

serve: site
	$(PYTHON) -m http.server 8000 --directory _site

clean:
	latexmk -C formula.tex
	latexmk -C competition.tex
	rm -r -f _site

help:
	@echo "make                 두 PDF와 전체 웹 사이트 빌드"
	@echo "make pdf             차량기술/경기진행 PDF 빌드"
	@echo "make site            기존 PDF를 포함해 웹 사이트 빌드"
	@echo "make site-without-pdf HTML/JSON만 검증 빌드"
	@echo "make check           단위/계약 테스트"
	@echo "make check-web       브라우저 사용성 테스트"
	@echo "make check-upstream  KSAE 공식 PDF 해시 확인"
	@echo "make serve           http://localhost:8000 에서 미리보기"

.PHONY: all pdf site site-without-pdf check check-web check-upstream serve clean help
