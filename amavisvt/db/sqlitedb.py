# -*- coding: utf-8 -*-
import logging
import sqlite3
import datetime

from amavisvt import patterns
from amavisvt.db.base import BaseDatabase

logger = logging.getLogger(__name__)

LATEST_SCHEMA_VERSION = 1

MIGRATIONS = (
	(), # version 0
	(  # version 1
		"CREATE TABLE `schema_version` (`version` INTEGER NOT NULL);",
		"INSERT INTO schema_version (version) VALUES (0);",
		"""CREATE TABLE `filenames` (
	`id`	INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
	`filename`	TEXT UNIQUE,
	`pattern`	TEXT,
	`infected`	INTEGER,
	`timestamp`	INTEGER,
	`sha256`	TEXT
);""",
	),
)

class AmavisVTDatabase(BaseDatabase):

	def connect(self):
		logger.debug("Connecting to database %s", self.db_path)
		self.conn = sqlite3.connect(self.db_path)
		self.check_schema()

	def check_schema(self):
		cursor = self.conn.cursor()

		schema_version = 0
		try:
			cursor.execute("SELECT version FROM schema_version")
			result = cursor.fetchone()
			schema_version = result[0]
			logger.debug("Schema version: %s", schema_version)
		except sqlite3.OperationalError:
			logger.info("Database not set up yet")

		if schema_version < LATEST_SCHEMA_VERSION:
			self.migrate_schema(schema_version)

	def close(self):
		logger.debug("Disconnecting database")
		if self.conn:
			try:
				self.conn.close()
			except:
				logger.exception("Could not close database connection")

	def migrate_schema(self, current_schema_version):
		for version in range(current_schema_version + 1, LATEST_SCHEMA_VERSION + 1):
			logger.info("Applying schema migrations for version %s" % version)

			for sql in MIGRATIONS[version]:
				logger.debug("Applying sql: %s", sql)

				cursor = self.conn.cursor()
				cursor.execute(sql)
				self.conn.commit()
				cursor.close()

			self.set_schema_version(version)

	def set_schema_version(self, version):
		logger.info("Setting database schema version to %s", version)
		cursor = self.conn.cursor()
		cursor.execute("UPDATE schema_version SET version=?", (version, ))
		self.conn.commit()
		cursor.close()

	def add_resource(self, resource):
		insert_sql = 'INSERT INTO filenames (filename, pattern, infected, "timestamp", sha256) VALUES (?, ?, ?, ?, ?)'
		update_sql = 'UPDATE filenames SET pattern = ?, timestamp = ? WHERE filename=?'

		pattern = patterns.calculate(resource.filename, self.get_filenames())

		values = (
			resource.filename,
			pattern,
			False,
			datetime.datetime.utcnow(),
			resource.sha256
		)

		cursor = None
		try:
			cursor = self.conn.cursor()
			cursor.execute(insert_sql, values)
		except sqlite3.IntegrityError:
			cursor.execute(update_sql, (pattern, datetime.datetime.utcnow(), resource.filename))
		finally:
			self.conn.commit()
			cursor.close()

	def get_filenames(self):
		cursor = self.conn.cursor()
		cursor.execute('SELECT DISTINCT filename FROM filenames')
		l = [x[0] for x in cursor.fetchall()]
		self.conn.commit()
		cursor.close()
		return l

	def update_patterns(self):
		logger.info("Updating patterns")
		sql = 'SELECT id, filename FROM filenames WHERE pattern IS NULL'

		cursor = self.conn.cursor()
		cursor.execute(sql)
		result = cursor.fetchall()
		self.conn.commit()
		cursor.close()

		update_sql = 'UPDATE filenames SET pattern=? WHERE id=?'
		other_filenames = self.get_filenames()

		for id, filename in result:
			pattern = patterns.calculate(filename, other_filenames)
			if pattern:
				logger.debug("Updating pattern for %s to %s", filename, pattern)
				cursor = self.conn.cursor()
				cursor.execute(update_sql, (
					pattern,
					id
				))
				self.conn.commit()
				cursor.close()

	def clean(self):
		min_date = datetime.datetime.now() - datetime.timedelta(days=90)
		sql = 'DELETE FROM filenames WHERE timestamp <= ?'

		cursor = self.conn.cursor()
		cursor.execute(sql, (min_date, ))
		self.conn.commit()
		cursor.close()