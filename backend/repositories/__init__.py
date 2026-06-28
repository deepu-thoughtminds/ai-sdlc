"""Data-access layer over MongoDB.

One module per collection. All Mongo queries live here so routers and services
call repository functions instead of embedding driver calls. Each function takes
the Database handle (from get_db / get_database) as its first argument and
returns Doc objects (attribute-accessible dicts) or plain values.
"""
