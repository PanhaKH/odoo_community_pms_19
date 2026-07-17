/* Local Ace SQL mode loaded as part of Odoo's existing web.ace_lib bundle. */
(function () {
    "use strict";
    // Ace derives its dynamic module URL from Odoo's hashed bundle URL. That
    // produces /web/assets/<hash>/mode-sql.js, which Odoo interprets as a
    // bundle name and rejects. Pin the fallback to this real static asset.
    ace.config.setModuleUrl(
        "ace/mode/sql",
        "/psql_query_execute/static/src/js/mode_sql.js"
    );
    ace.config.setModuleUrl(
        "ace/mode/sql_highlight_rules",
        "/psql_query_execute/static/src/js/mode_sql.js"
    );
    ace.define(
        "ace/mode/sql_highlight_rules",
        ["require", "exports", "module", "ace/lib/oop", "ace/mode/text_highlight_rules"],
        function (require, exports) {
            const oop = require("ace/lib/oop");
            const TextHighlightRules = require("ace/mode/text_highlight_rules").TextHighlightRules;
            const SqlHighlightRules = function () {
                const keywords = (
                    "select|from|where|with|as|distinct|all|join|inner|left|right|full|outer|cross|on|" +
                    "group|by|having|order|asc|desc|nulls|first|last|limit|offset|fetch|union|intersect|" +
                    "except|case|when|then|else|end|and|or|not|in|is|null|true|false|like|ilike|between|" +
                    "exists|any|some|over|partition|rows|range|current|row|preceding|following|explain"
                );
                const functions = (
                    "count|sum|avg|min|max|coalesce|nullif|cast|extract|date_trunc|now|current_database|" +
                    "current_user|lower|upper|substring|length|round|json_build_object|json_agg|array_agg"
                );
                const mapper = this.createKeywordMapper(
                    { "keyword": keywords, "support.function": functions },
                    "identifier",
                    true
                );
                this.$rules = {
                    start: [
                        { token: "comment", regex: "--.*$" },
                        { token: "comment", start: "/\\*", end: "\\*/" },
                        { token: "string", regex: "'(?:''|[^'])*'" },
                        { token: "string", regex: '"(?:""|[^"])*"' },
                        { token: "constant.numeric", regex: "\\b(?:0[xX][0-9a-fA-F]+|\\d+(?:\\.\\d+)?)\\b" },
                        { token: mapper, regex: "[A-Za-z_][A-Za-z0-9_$]*\\b" },
                        { token: "keyword.operator", regex: "<>|!=|<=|>=|::|[-+*/%=<>&|]" },
                        { token: "paren.lparen", regex: "[\\(]" },
                        { token: "paren.rparen", regex: "[\\)]" },
                        { token: "text", regex: "\\s+" },
                    ],
                };
                this.normalizeRules();
            };
            oop.inherits(SqlHighlightRules, TextHighlightRules);
            exports.SqlHighlightRules = SqlHighlightRules;
        }
    );
    ace.define(
        "ace/mode/sql",
        ["require", "exports", "module", "ace/lib/oop", "ace/mode/text", "ace/mode/sql_highlight_rules"],
        function (require, exports) {
            const oop = require("ace/lib/oop");
            const TextMode = require("ace/mode/text").Mode;
            const SqlHighlightRules = require("ace/mode/sql_highlight_rules").SqlHighlightRules;
            const Mode = function () {
                this.HighlightRules = SqlHighlightRules;
                this.lineCommentStart = "--";
                this.blockComment = { start: "/*", end: "*/" };
                this.$behaviour = this.$defaultBehaviour;
            };
            oop.inherits(Mode, TextMode);
            Mode.prototype.$id = "ace/mode/sql";
            exports.Mode = Mode;
        }
    );
})();
