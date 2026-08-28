package net.jethachan.factory_badges.transition;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Minimal duplicate-key-rejecting JSON parser plus the handoff's canonical encoder. */
final class CanonicalJson {
    private static final int MAX_DEPTH = 16;

    private CanonicalJson() {}

    static Map<String, Object> parseCanonicalObject(byte[] data) {
        if (data == null || data.length == 0) {
            throw new IllegalArgumentException("canonical JSON must not be empty");
        }
        for (byte item : data) {
            if ((item & 0x80) != 0) {
                throw new IllegalArgumentException("canonical JSON must be ASCII");
            }
        }
        String source = new String(data, StandardCharsets.US_ASCII);
        Parser parser = new Parser(source);
        Object value = parser.parseValue(0);
        parser.skipWhitespace();
        if (!parser.atEnd()) {
            throw new IllegalArgumentException("trailing JSON data");
        }
        if (!(value instanceof Map)) {
            throw new IllegalArgumentException("canonical JSON root must be an object");
        }
        StringBuilder encoded = new StringBuilder(data.length);
        encode(value, encoded, 0);
        encoded.append('\n');
        if (!source.equals(encoded.toString())) {
            throw new IllegalArgumentException("JSON is not in the canonical handoff encoding");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> object = (Map<String, Object>) value;
        return object;
    }

    private static void encode(Object value, StringBuilder output, int indent) {
        if (value instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> object = (Map<String, Object>) value;
            if (object.isEmpty()) {
                output.append("{}");
                return;
            }
            List<String> keys = new ArrayList<String>(object.keySet());
            Collections.sort(keys, Comparator.naturalOrder());
            output.append("{\n");
            for (int index = 0; index < keys.size(); index++) {
                spaces(output, indent + 2);
                encodeString(keys.get(index), output);
                output.append(": ");
                encode(object.get(keys.get(index)), output, indent + 2);
                output.append(index + 1 == keys.size() ? '\n' : ",\n");
            }
            spaces(output, indent);
            output.append('}');
        } else if (value instanceof List) {
            @SuppressWarnings("unchecked")
            List<Object> array = (List<Object>) value;
            if (array.isEmpty()) {
                output.append("[]");
                return;
            }
            output.append("[\n");
            for (int index = 0; index < array.size(); index++) {
                spaces(output, indent + 2);
                encode(array.get(index), output, indent + 2);
                output.append(index + 1 == array.size() ? '\n' : ",\n");
            }
            spaces(output, indent);
            output.append(']');
        } else if (value instanceof String) {
            encodeString((String) value, output);
        } else if (value instanceof Long) {
            output.append(((Long) value).longValue());
        } else if (value instanceof Boolean) {
            output.append(((Boolean) value).booleanValue() ? "true" : "false");
        } else if (value == null) {
            output.append("null");
        } else {
            throw new IllegalArgumentException("unsupported canonical JSON value");
        }
    }

    private static void encodeString(String value, StringBuilder output) {
        output.append('"');
        for (int index = 0; index < value.length(); index++) {
            char item = value.charAt(index);
            switch (item) {
                case '"': output.append("\\\""); break;
                case '\\': output.append("\\\\"); break;
                case '\b': output.append("\\b"); break;
                case '\f': output.append("\\f"); break;
                case '\n': output.append("\\n"); break;
                case '\r': output.append("\\r"); break;
                case '\t': output.append("\\t"); break;
                default:
                    if (item < 0x20) {
                        output.append("\\u00");
                        output.append(Character.forDigit((item >>> 4) & 0xF, 16));
                        output.append(Character.forDigit(item & 0xF, 16));
                    } else if (item > 0x7F) {
                        throw new IllegalArgumentException(
                                "canonical handoff strings must be ASCII");
                    } else {
                        output.append(item);
                    }
            }
        }
        output.append('"');
    }

    private static void spaces(StringBuilder output, int count) {
        for (int index = 0; index < count; index++) output.append(' ');
    }

    private static final class Parser {
        private final String source;
        private int offset;

        Parser(String source) {
            this.source = source;
        }

        boolean atEnd() {
            return offset == source.length();
        }

        void skipWhitespace() {
            while (!atEnd()) {
                char item = source.charAt(offset);
                if (item != ' ' && item != '\n' && item != '\r' && item != '\t') return;
                offset++;
            }
        }

        Object parseValue(int depth) {
            if (depth > MAX_DEPTH) {
                throw new IllegalArgumentException("JSON nesting exceeds limit");
            }
            skipWhitespace();
            if (atEnd()) throw new IllegalArgumentException("truncated JSON");
            char item = source.charAt(offset);
            if (item == '{') return parseObject(depth + 1);
            if (item == '[') return parseArray(depth + 1);
            if (item == '"') return parseString();
            if (item == 't') return literal("true", Boolean.TRUE);
            if (item == 'f') return literal("false", Boolean.FALSE);
            if (item == 'n') return literal("null", null);
            if (item == '-' || (item >= '0' && item <= '9')) return parseInteger();
            throw new IllegalArgumentException("invalid JSON token");
        }

        private Map<String, Object> parseObject(int depth) {
            offset++;
            LinkedHashMap<String, Object> result = new LinkedHashMap<String, Object>();
            skipWhitespace();
            if (consume('}')) return result;
            while (true) {
                skipWhitespace();
                if (atEnd() || source.charAt(offset) != '"') {
                    throw new IllegalArgumentException("object key must be a string");
                }
                String key = parseString();
                if (result.containsKey(key)) {
                    throw new IllegalArgumentException("duplicate JSON key: " + key);
                }
                skipWhitespace();
                require(':');
                result.put(key, parseValue(depth));
                skipWhitespace();
                if (consume('}')) return result;
                require(',');
            }
        }

        private List<Object> parseArray(int depth) {
            offset++;
            List<Object> result = new ArrayList<Object>();
            skipWhitespace();
            if (consume(']')) return result;
            while (true) {
                result.add(parseValue(depth));
                skipWhitespace();
                if (consume(']')) return result;
                require(',');
            }
        }

        private String parseString() {
            require('"');
            StringBuilder result = new StringBuilder();
            while (!atEnd()) {
                char item = source.charAt(offset++);
                if (item == '"') return result.toString();
                if (item < 0x20) {
                    throw new IllegalArgumentException("unescaped control in JSON string");
                }
                if (item != '\\') {
                    result.append(item);
                    continue;
                }
                if (atEnd()) throw new IllegalArgumentException("truncated JSON escape");
                char escaped = source.charAt(offset++);
                switch (escaped) {
                    case '"': result.append('"'); break;
                    case '\\': result.append('\\'); break;
                    case '/': result.append('/'); break;
                    case 'b': result.append('\b'); break;
                    case 'f': result.append('\f'); break;
                    case 'n': result.append('\n'); break;
                    case 'r': result.append('\r'); break;
                    case 't': result.append('\t'); break;
                    case 'u': result.append(parseUnicode()); break;
                    default: throw new IllegalArgumentException("invalid JSON escape");
                }
            }
            throw new IllegalArgumentException("unterminated JSON string");
        }

        private char parseUnicode() {
            if (offset + 4 > source.length()) {
                throw new IllegalArgumentException("truncated JSON unicode escape");
            }
            int value = 0;
            for (int index = 0; index < 4; index++) {
                int digit = Character.digit(source.charAt(offset++), 16);
                if (digit < 0) throw new IllegalArgumentException("invalid JSON unicode escape");
                value = (value << 4) | digit;
            }
            return (char) value;
        }

        private Long parseInteger() {
            int start = offset;
            if (source.charAt(offset) == '-') offset++;
            if (atEnd()) throw new IllegalArgumentException("truncated JSON number");
            if (source.charAt(offset) == '0') {
                offset++;
                if (!atEnd() && Character.isDigit(source.charAt(offset))) {
                    throw new IllegalArgumentException("JSON integer has a leading zero");
                }
            } else {
                if (source.charAt(offset) < '1' || source.charAt(offset) > '9') {
                    throw new IllegalArgumentException("invalid JSON integer");
                }
                while (!atEnd() && Character.isDigit(source.charAt(offset))) offset++;
            }
            if (!atEnd()) {
                char suffix = source.charAt(offset);
                if (suffix == '.' || suffix == 'e' || suffix == 'E') {
                    throw new IllegalArgumentException("canonical handoff uses integers only");
                }
            }
            try {
                return Long.valueOf(source.substring(start, offset));
            } catch (NumberFormatException error) {
                throw new IllegalArgumentException("JSON integer is out of range", error);
            }
        }

        private Object literal(String text, Object value) {
            if (!source.startsWith(text, offset)) {
                throw new IllegalArgumentException("invalid JSON literal");
            }
            offset += text.length();
            return value;
        }

        private boolean consume(char expected) {
            if (!atEnd() && source.charAt(offset) == expected) {
                offset++;
                return true;
            }
            return false;
        }

        private void require(char expected) {
            if (!consume(expected)) {
                throw new IllegalArgumentException("expected JSON token " + expected);
            }
        }
    }
}
