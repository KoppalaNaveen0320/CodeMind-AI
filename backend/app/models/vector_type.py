import struct
from typing import Any, List, Optional
from sqlalchemy.types import UserDefinedType, Float, TypeEngine
from sqlalchemy import Dialect, Operators
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement, literal


class pg_vector_cast(FunctionElement):
    inherit_cache = True


@compiles(pg_vector_cast, "postgresql")
def _compile_pg_vector_cast_pg(element, compiler, **kw):
    arg = compiler.process(element.clauses.clauses[0], **kw)
    dim = element.clauses.clauses[1].value if len(element.clauses.clauses) > 1 else None
    if dim:
        return f"CAST({arg} AS vector({dim}))"
    return f"CAST({arg} AS vector)"


@compiles(pg_vector_cast)
def _compile_pg_vector_cast_default(element, compiler, **kw):
    return compiler.process(element.clauses.clauses[0], **kw)


class RobustVector(UserDefinedType[Any]):
    """
    Robust pgvector Vector TypeEngine for SQLAlchemy.
    Supports PostgreSQL (pgvector binary/hex and array_to_vector coercion) and SQLite fallback.
    Prevents the 12,379 dimension mismatch bug caused by ASCII string serialization in Windows/binary environments.
    """
    cache_ok = True

    def __init__(self, dim: Optional[int] = None) -> None:
        super().__init__()
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        if self.dim is None:
            return "VECTOR"
        return f"VECTOR({self.dim})"

    def bind_processor(self, dialect: Dialect) -> Any:
        def process(value: Any) -> Any:
            if value is None:
                return None
            if hasattr(value, "tolist"):
                value = value.tolist()
            if isinstance(value, (list, tuple)):
                if dialect.name == "postgresql":
                    return [float(x) for x in value]
                else:
                    return f"[{','.join(str(float(x)) for x in value)}]"
            return value
        return process

    def bind_expression(self, bindparam: Any) -> Any:
        return pg_vector_cast(bindparam, literal(self.dim))

    def result_processor(self, dialect: Dialect, coltype: Any) -> Any:
        def process(value: Any) -> Optional[List[float]]:
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return list(value)
            if isinstance(value, str):
                s = value.strip()
                if s.startswith("\\x") or s.startswith("x") or (len(s) > 4 and all(c in "0123456789abcdefABCDEF" for c in s[:10])):
                    hex_data = s[2:] if s.startswith("\\x") else (s[1:] if s.startswith("x") else s)
                    try:
                        raw_bytes = bytes.fromhex(hex_data)
                        dim = struct.unpack_from("<H", raw_bytes, 0)[0]
                        return list(struct.unpack_from(f"<{dim}f", raw_bytes, 4))
                    except Exception:
                        pass
                if s.startswith("[") and s.endswith("]"):
                    s = s[1:-1].strip()
                    if not s:
                        return []
                    return [float(x) for x in s.split(",")]
            return value
        return process

    class Comparator(TypeEngine.Comparator[Any]):
        def cosine_distance(self, other: Any) -> Operators:
            return self.op("<=>", return_type=Float)(pg_vector_cast(other, literal(self.type.dim)))

        def l2_distance(self, other: Any) -> Operators:
            return self.op("<->", return_type=Float)(pg_vector_cast(other, literal(self.type.dim)))

        def max_inner_product(self, other: Any) -> Operators:
            return self.op("<#>", return_type=Float)(pg_vector_cast(other, literal(self.type.dim)))

    comparator_factory = Comparator
