NAME = packages_bot
BINDIR ?= /usr/bin
SERVICEDIR ?= /usr/lib/systemd/user

install:
	cp -p $(NAME).py $(DESTDIR)$(BINDIR)
	cp -p $(NAME).timer $(DESTDIR)$(SERVICEDIR)
	cp -p $(NAME).service $(DESTDIR)$(SERVICEDIR)

uninstall:
	rm $(DESTDIR)$(BINDIR)/$(NAME).py
	rm $(DESTDIR)$(SERVICEDIR)/$(NAME).timer
	rm $(DESTDIR)$(SERVICEDIR)/$(NAME).service
