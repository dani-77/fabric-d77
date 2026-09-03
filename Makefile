DESTDIR   ?=

PAM_DIR    ?= /etc/pam.d
PAM_FILE    = pam/fabric-d77

BIN_DIR    ?= /usr/bin
BIN_FILE    = bin/fabric-d77-signal
WRAPPER_FILE = bin/fabric-d77

SHARE_DIR  ?= /usr/share/fabric-d77

.PHONY: install uninstall

# Mirrors what srcpkgs/fabric-d77/template's do_install() actually ships
# (vcopy "*.py" + assets + style.css, plus the two /usr/bin wrappers and the
# PAM file) — this used to only install the PAM file and fabric-d77-signal,
# silently leaving the *.py shell code (main.py, ollama_chat.py, ...)
# unsynced: `sudo make install` looked like a full deploy but never touched
# what's actually running from /usr/share/fabric-d77.
install:
	install -Dm644 $(PAM_FILE) $(DESTDIR)$(PAM_DIR)/fabric-d77
	install -Dm755 $(BIN_FILE) $(DESTDIR)$(BIN_DIR)/fabric-d77-signal
	install -Dm755 $(WRAPPER_FILE) $(DESTDIR)$(BIN_DIR)/fabric-d77
	install -d $(DESTDIR)$(SHARE_DIR)
	install -m644 *.py $(DESTDIR)$(SHARE_DIR)/
	cp -a assets $(DESTDIR)$(SHARE_DIR)/
	install -m644 style.css $(DESTDIR)$(SHARE_DIR)/

uninstall:
	rm -f $(DESTDIR)$(PAM_DIR)/fabric-d77
	rm -f $(DESTDIR)$(BIN_DIR)/fabric-d77-signal
	rm -f $(DESTDIR)$(BIN_DIR)/fabric-d77
	rm -rf $(DESTDIR)$(SHARE_DIR)
