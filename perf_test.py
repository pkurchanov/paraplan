from time import perf_counter

start = perf_counter()
import parser  # noqa: E402

parser.parse()
end = perf_counter()

print(f"Parsing time: {(end - start) * 10**3:.1f} milliseconds")
