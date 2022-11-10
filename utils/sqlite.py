import sqlite3


def dict_factory(cursor, row):
    return {col[0]: row[index] for index, col in enumerate(cursor.description)}


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(
            "storage.db", isolation_level=None, detect_types=sqlite3.PARSE_DECLTYPES
        )
        self.conn.row_factory = dict_factory
        self.db = self.conn.cursor()

    def execute(self, sql: str, prepared: tuple = (), commit: bool = True):
        """ Execute SQL command with args for 'Prepared Statements' """
        try:
            data = self.db.execute(sql, prepared)
        except Exception as e:
            return f"{type(e).__name__}: {e}"

        status_word = sql.split(' ')[0].upper()
        status_code = max(data.rowcount, 0)
        if status_word == "SELECT":
            status_code = len(data.fetchall())

        return f"{status_word} {status_code}"

    def create_tables(self):
        query = """
        CREATE TABLE IF NOT EXISTS whitelist (
            guild_id BIGINT NOT NULL,
            whitelist BOOLEAN NOT NULL DEFAULT true,
            invited BOOLEAN NOT NULL DEFAULT false,
            granted_by BIGINT NOT NULL,
            revoked_by BIGINT,
            PRIMARY KEY (guild_id)
        );
        """

        return self.execute(query)

    def fetch(self, sql: str, prepared: tuple = ()):
        """ Fetch DB data with args for 'Prepared Statements' """
        return self.db.execute(sql, prepared).fetchall()

    def fetchrow(self, sql: str, prepared: tuple = ()):
        """ Fetch DB row (one row only) with args for 'Prepared Statements' """
        return self.db.execute(sql, prepared).fetchone()
