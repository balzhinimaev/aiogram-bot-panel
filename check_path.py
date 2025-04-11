import sys
import pprint # Для красивого вывода

print("--- Python Executable ---")
print(sys.executable) # Показывает, какой Python используется
print("\n--- sys.path ---")
pprint.pprint(sys.path) # Показывает все пути, где Python ищет модули