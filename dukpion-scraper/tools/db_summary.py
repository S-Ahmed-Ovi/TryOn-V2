import sqlite3
c = sqlite3.connect("dataset/dukpion.db")
for row in c.execute("select download_status, coalesce(error,'-'), count(*) from images where download_status!='pending' group by 1,2"):
    print(row)
