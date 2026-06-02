# check_cupy.py
import sys

print(f"--- Checking CuPy with Python from: {sys.executable} ---")
print(f"--- Python Version: {sys.version} ---")

try:
    import cupy
    print("\n--- CuPy Import Successful ---")
    print("--- Running cupy.show_config() ---\n")
    # Using print() ensures the entire output is captured.
    print(cupy.show_config())

except ImportError as e:
    print("\n--- CUPY IMPORT FAILED ---")
    print(f"Error: {e}")
    print("\nCuPy could not be imported. Please ensure it is installed correctly for your Python environment.")

except Exception as e:
    print("\n--- AN UNEXPECTED ERROR OCCURRED ---")
    import traceback
    traceback.print_exc()

print("\n--- Check Complete ---")