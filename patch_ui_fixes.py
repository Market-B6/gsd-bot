#!/usr/bin/env python3
"""Патч UI: меню-кнопки прерывают активный сценарий (fix #2).
Никакого placeholder/ForceReply — поле ввода не трогаем.
Правит только диари-флоу в app/bot/handlers.py. Идемпотентен, .bak, py_compile."""
import shutil, py_compile, sys

F = "app/bot/handlers.py"
src = open(F, encoding="utf-8").read()

if "MENU_BUTTONS" in src:
    print("SKIP: уже применён (MENU_BUTTONS найден)")
    sys.exit(0)

def repl(text, old, new):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: якорь встречается {n} раз, ожидалось 1:\n{old[:80]}")
        sys.exit(1)
    return text.replace(old, new)

# 1) Константа с подписями кнопок меню — перед get_main_keyboard
src = repl(src,
    "# Keyboards\ndef get_main_keyboard():",
    'MENU_BUTTONS = frozenset({\n'
    '    "\U0001F37D Приём пищи",\n'
    '    "\U0001FA78 Замер сахара",\n'
    '    "\U0001F489 Инсулин",\n'
    '    "\U0001F4CA Мой дневник",\n'
    '    "❓ Помощь",\n'
    '    "✉️ Написать нам",\n'
    '})\n\n'
    "# Keyboards\ndef get_main_keyboard():")

# 2) Meal flow
src = repl(src,
    "@router.message(MealState.waiting_for_description)\n",
    "@router.message(MealState.waiting_for_description, ~F.text.in_(MENU_BUTTONS))\n")
src = repl(src,
    "@router.message(MealState.waiting_for_time)\n",
    "@router.message(MealState.waiting_for_time, ~F.text.in_(MENU_BUTTONS))\n")

# 3) Glucose flow
src = repl(src,
    "@router.message(GlucoseState.waiting_for_value)\n",
    "@router.message(GlucoseState.waiting_for_value, ~F.text.in_(MENU_BUTTONS))\n")
src = repl(src,
    "@router.message(GlucoseState.waiting_for_time)\n",
    "@router.message(GlucoseState.waiting_for_time, ~F.text.in_(MENU_BUTTONS))\n")

# 4) Insulin flow
src = repl(src,
    "@router.message(InsulinState.waiting_for_units)\n",
    "@router.message(InsulinState.waiting_for_units, ~F.text.in_(MENU_BUTTONS))\n")
src = repl(src,
    "@router.message(InsulinState.waiting_for_time)\n",
    "@router.message(InsulinState.waiting_for_time, ~F.text.in_(MENU_BUTTONS))\n")

# 5) Support flow
src = repl(src,
    "@router.message(SupportState.waiting_for_message)\n",
    "@router.message(SupportState.waiting_for_message, ~F.text.in_(MENU_BUTTONS))\n")

shutil.copy(F, F + ".bak")
open(F, "w", encoding="utf-8").write(src)
py_compile.compile(F, doraise=True)
print("OK: fix #2 применён, файл скомпилирован, бэкап в handlers.py.bak")
