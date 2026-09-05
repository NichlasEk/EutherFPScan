CC = cc
CFLAGS = -O2 -Wall -Wextra -Werror

.PHONY: all test
all: build/euther-capture

build/euther-capture: src/capture.c src/vfs_pipe.c
	mkdir -p build
	$(CC) $(CFLAGS) $^ -o $@ -Wl,--export-dynamic-symbol=palPipeRead -ldl

test: all
	python3 -m unittest discover -s tests -v
