.PHONY: build build-clean install

build:
	pyinstaller --onefile --name fin \
		--hidden-import fin \
		--hidden-import fin.models \
		--hidden-import fin.db \
		--hidden-import fin.helpers \
		--hidden-import fin.seed \
		--hidden-import fin.services \
		--hidden-import fin.services.amortization \
		--hidden-import fin.services.onboarding \
		--hidden-import sqlalchemy \
		--hidden-import sqlalchemy.orm \
		--hidden-import mcp \
		--hidden-import mcp.server.fastmcp \
		src/fin/mcp_server.py

build-clean: build
	rm -rf build/ fin.spec

install: build-clean
	mkdir -p ~/.fin/bin
	cp dist/fin ~/.fin/bin/fin
	chmod +x ~/.fin/bin/fin
	@echo "Binary installed to ~/.fin/bin/fin"
	@echo "Use in MCP config: \"command\": \"$$HOME/.fin/bin/fin\""
