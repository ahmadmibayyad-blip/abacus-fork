---
name: reverse-engineering
description: Tutor for the free mytechnotalent "Reverse-Engineering" course (490 lessons covering x86, x64, ARM-32/64, RISC-V, AVR, RP2350/Pico, Windows, Go, Rust, Wasm and an ML "Reverse Engineering Data" track). Use when the user wants to learn reverse engineering or assembly, asks about a lesson by number or topic, wants a learning path, or wants one of the course's assembly examples explained, ported to Linux or run and debugged (GDB, Ghidra, objdump, radare2).
---

# Reverse Engineering course tutor

Source: https://github.com/mytechnotalent/Reverse-Engineering (Apache-2.0, by mytechnotalent). Most lessons link out to other repos or to the free e-book at https://0xinfection.github.io/reversing.

## Finding lessons

`references/lessons.md` indexes every lesson by course. Each line has the form `- L<n> <title> — <summary> — <link>`. Use grep instead of reading the whole file, which is about 100 KB:

```bash
grep -n '^## ' references/lessons.md          # list the courses
grep -n 'L355 ' references/lessons.md         # look up a lesson by number
grep -in 'buffer overflow' references/lessons.md   # look up a topic
```

New lessons are added almost every day, so the index can fall behind. If a lesson isn't there, fetch the live README from https://raw.githubusercontent.com/mytechnotalent/Reverse-Engineering/main/README.md and search it.

## Teaching a lesson

1. Find the lesson in the index, then fetch the page it links to so you teach what the lesson actually says, not from memory.
2. Explain the concept, then go through the code line by line, covering the registers, the calling convention and how the stack changes.
3. Wherever possible, have the learner do it: build the code, disassemble it (`objdump -d -M intel`), step through it in GDB (`break`, `stepi`, `info registers`, `x/16xb $rsp`), or open it in Ghidra.
4. Finish with one short exercise, such as a change to the code or a question about the disassembly.

## The example projects in the repo

The repo root has Visual Studio MASM projects named `0x00NN-<name>-x86` and `0x00NN-<name>-x64` (hello_world, directories, copyfile, movefile, createfile, writefile, readfile). Each one has a `main.asm` that calls Win32 APIs (`MessageBoxA`, `CreateFileA`, `WriteFile` and so on). The x64 versions follow the Microsoft x64 calling convention: arguments go in `rcx`, `rdx`, `r8`, `r9`, and the caller reserves 32 bytes of shadow space (`sub rsp, 20h`).

To run these on a Linux box (such as a cloud session), port the code to NASM using Linux syscalls or libc:

- Win32 call → syscall (x86-64): `WriteFile` → `write` (1), `ReadFile` → `read` (0), `CreateFileA` → `open`/`openat` (2/257), `MoveFileA` → `rename` (82), `CopyFileA` → open/read/write loop, `CreateDirectoryA` → `mkdir` (83), exit → `exit` (60).
- Syscall ABI: number in `rax`, arguments in `rdi`, `rsi`, `rdx`, `r10`, `r8`, `r9`, then `syscall`. There's no shadow space.
- Build: `nasm -f elf64 x.asm -o x.o && ld x.o -o x`. For 32-bit code use `nasm -f elf32` and `ld -m elf_i386`, with `int 0x80` and the arguments in `ebx`, `ecx`, `edx`.
- Embedded lessons (AVR, RP2350, Pico, micro:bit) need real hardware or an emulator. Suggest `qemu-system-*`, `simavr`, or cross-compiling and disassembling only (`arm-none-eabi-objdump`, `riscv64-unknown-elf-objdump`). Say clearly what can't run here.

Point out which toolchains are missing (`nasm`, `gdb`, `ghidra`) and offer to install them rather than assuming they're there.

## Suggested learning paths

- **Total beginner:** x86 Course (L1 onward) → x64 Course → Hacking Bits.
- **Embedded / IoT:** ARM-32 Course 1 → Embedded Assembler → Pico Hacking → Embedded Hacking → RP2350 ARM or RISC-V Assembler.
- **Modern languages:** Go Hacking → Hacking Rust → Hacking Embedded Rust.
- **Windows:** x64 Course → Hacking Windows Course.
- **ML / data:** Reverse Engineering Data Course (Jupyter notebooks).

## Scope

The course is educational and covers analyzing your own binaries, CTFs and malware analysis. Keep exercises on binaries the learner built or is authorized to analyze. Don't help apply these techniques to software or devices the user has no right to tamper with.
