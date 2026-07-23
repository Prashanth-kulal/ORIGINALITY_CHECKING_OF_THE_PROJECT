const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');

const dbPath = path.join(__dirname, 'evaluation_system.db');
const schemaPath = path.join(__dirname, '..', 'database', 'schema.sql');

const db = new sqlite3.Database(dbPath, (err) => {
    if (err) {
        console.error('Error connecting to SQLite database:', err.message);
    } else {
        console.log('Connected to standalone SQLite database at:', dbPath);
        initSchema();
    }
});

function initSchema() {
    if (fs.existsSync(schemaPath)) {
        const schema = fs.readFileSync(schemaPath, 'utf8');
        db.exec(schema, (err) => {
            if (err) {
                console.error('Error initializing schema:', err.message);
            } else {
                console.log('Database schema initialized successfully.');
            }
        });
    }
}

module.exports = db;
