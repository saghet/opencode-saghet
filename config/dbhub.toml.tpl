[[sources]]
id = "sqlite_ro"
type = "sqlite"
database = "__SAGHET_HOME__/.local/share/oade/databases/oade_lab.db"

[[sources]]
id = "sqlite_rw"
type = "sqlite"
database = "__SAGHET_HOME__/.local/share/oade/databases/oade_lab.db"

[[sources]]
id = "pg_ro"
type = "postgres"
host = "127.0.0.1"
port = 5432
database = "oade_dev"
user = "oade_reader"
password = "${OADE_PG_READER_PASS}"

[[sources]]
id = "pg_rw"
type = "postgres"
host = "127.0.0.1"
port = 5432
database = "oade_dev"
user = "oade_writer"
password = "${OADE_PG_WRITER_PASS}"

[[tools]]
name = "execute_sql"
source = "sqlite_ro"
readonly = true
max_rows = 200

[[tools]]
name = "search_objects"
source = "sqlite_ro"

[[tools]]
name = "execute_sql"
source = "sqlite_rw"
readonly = false
max_rows = 500

[[tools]]
name = "execute_sql"
source = "pg_ro"
readonly = true
max_rows = 200

[[tools]]
name = "search_objects"
source = "pg_ro"

[[tools]]
name = "execute_sql"
source = "pg_rw"
readonly = false
max_rows = 500
