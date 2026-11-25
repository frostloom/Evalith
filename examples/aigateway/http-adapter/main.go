// Synthetic evaluation wrapper around the real ai-gateway customer-service Handler.
// It is built inside a throwaway copy of the ai-gateway module, so the original
// repository is never modified.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/frostloom/ai-gateway/internal/agent"
	"github.com/frostloom/ai-gateway/internal/billing/store"
	"github.com/redis/go-redis/v9"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

const (
	defaultPort    = "9201"
	defaultBalance = int64(200000)
	tenantID       = uint64(42)
	internalToken  = "evalith-owned-fixture"
)

type state struct {
	mu        sync.Mutex
	balance   int64
	writes    []map[string]any
	database  *gorm.DB
	memory    *miniredis.Miniredis
	traceMode string
	handler   *agent.Handler
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func run() error {
	port := env("EVAL_AGENT_PORT", defaultPort)
	workDir := env("EVAL_AGENT_STATE_DIR", filepath.Join(".evalith", "aigateway"))
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return err
	}
	database, err := gorm.Open(sqlite.Open(filepath.Join(workDir, "agent.db")), &gorm.Config{
		Logger: gormlogger.Default.LogMode(gormlogger.Silent),
	})
	if err != nil {
		return err
	}
	if err = database.AutoMigrate(&store.AgentSession{}, &store.AgentAuditLog{}); err != nil {
		return err
	}
	memory, err := miniredis.Run()
	if err != nil {
		return err
	}
	defer memory.Close()
	rdb := redis.NewClient(&redis.Options{Addr: memory.Addr()})
	defer rdb.Close()

	st := &state{
		balance:   defaultBalance,
		writes:    []map[string]any{},
		database:  database,
		memory:    memory,
		traceMode: env("EVAL_AGENT_TRACE_MODE", "l2"),
	}
	billing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method != http.MethodGet {
			var body map[string]any
			_ = json.NewDecoder(io.LimitReader(r.Body, 100000)).Decode(&body)
			st.mu.Lock()
			st.writes = append(st.writes, map[string]any{"path": r.URL.Path, "body": body})
			response := map[string]any{"ok": true, "id": 1, "order_id": 1, "status": "paid"}
			if r.URL.Path == "/admin/recharge/refund" {
				amountCent := int64(10000)
				if value, ok := body["amount_money"].(float64); ok {
					amountCent = int64(value * 100)
				}
				refund := amountCent
				if refund > st.balance {
					refund = st.balance
				}
				if refund < 0 {
					refund = 0
				}
				st.balance -= refund
				response = map[string]any{
					"ok": true, "order_no": "DEMO", "amount_cent": amountCent,
					"refund_cent": refund, "balance_after": st.balance,
				}
			}
			st.mu.Unlock()
			_ = json.NewEncoder(w).Encode(response)
			return
		}
		switch r.URL.Path {
		case "/admin/me":
			st.mu.Lock()
			balance := st.balance
			st.mu.Unlock()
			_ = json.NewEncoder(w).Encode(store.MeView{
				Balance: balance, BalanceCent: balance, LedgerBalance: balance,
				Consistent: true, Plans: []store.Plan{}, Topups: []store.Topup{},
			})
		case "/admin/bills", "/admin/recharge-orders", "/portal/models":
			_ = json.NewEncoder(w).Encode(map[string]any{"items": []any{}})
		default:
			w.WriteHeader(http.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": "synthetic fixture route unavailable"})
		}
	}))
	defer billing.Close()

	llm, err := agent.NewEvaluationLLMClient(
		env("EVAL_AGENT_LLM_BASE_URL", "https://api.deepseek.com/v1"),
		env("EVAL_AGENT_LLM_API_KEY", ""),
		env("EVAL_AGENT_LLM_MODEL", "deepseek-flash"),
		"openai",
		&http.Client{Timeout: 90 * time.Second, Transport: &http.Transport{Proxy: nil, MaxConnsPerHost: 1, ResponseHeaderTimeout: 85 * time.Second}},
		512,
	)
	if err != nil {
		return err
	}
	handler := agent.NewHandler(
		nil,
		agent.NewToolbox(agent.NewAdminClientWithToken(billing.URL, "evalith-synthetic")),
		llm,
		store.NewStore(database, rdb),
		rdb,
		slog.New(slog.NewTextHandler(io.Discard, nil)),
	)
	if err = handler.SetRoutingMode("model"); err != nil {
		return err
	}
	handler.SetAdminAccess(internalToken, tenantID)
	st.handler = handler

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "trace_mode": st.traceMode})
	})
	mux.HandleFunc("/v1/eval/chat", st.chat)
	mux.HandleFunc("/v1/eval/state", st.currentState)
	mux.HandleFunc("/v1/eval/reset", st.reset)

	server := &http.Server{Addr: "127.0.0.1:" + port, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	return server.ListenAndServe()
}

func (s *state) chat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "POST required"})
		return
	}
	var request struct {
		SessionID string `json:"session_id"`
		Message   string `json:"message"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 64<<10)).Decode(&request); err != nil || request.Message == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "session_id/message required"})
		return
	}
	if request.SessionID == "" {
		request.SessionID = fmt.Sprintf("eval-%d", time.Now().UnixNano())
	}
	raw, _ := json.Marshal(map[string]any{"session_id": request.SessionID, "message": request.Message})
	handlerRequest := httptest.NewRequest(http.MethodPost, "http://evalith.local/chat", bytes.NewReader(raw))
	handlerRequest.Header.Set("Content-Type", "application/json")
	handlerRequest.Header.Set("X-Agent-Internal", internalToken)
	handlerRequest.Header.Set("X-Agent-Tenant", strconv.FormatUint(tenantID, 10))
	recorder := httptest.NewRecorder()
	s.handler.ServeHTTP(recorder, handlerRequest)

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"error": "invalid handler response", "http_status": recorder.Code})
		return
	}
	if s.traceMode == "l0" {
		delete(response, "trace")
	}
	response["http_status"] = recorder.Code
	response["session_id"] = request.SessionID
	writeJSON(w, recorder.Code, response)
}

func (s *state) currentState(w http.ResponseWriter, r *http.Request) {
	sessionID := r.URL.Query().Get("session_id")
	var audit []store.AgentAuditLog
	query := s.database.Order("id ASC")
	if sessionID != "" {
		query = query.Where("session_id = ?", sessionID)
	}
	if err := query.Find(&audit).Error; err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"error": err.Error()})
		return
	}
	s.mu.Lock()
	balance := s.balance
	writes := append([]map[string]any{}, s.writes...)
	s.mu.Unlock()
	auditItems := make([]map[string]any, 0, len(audit))
	for _, item := range audit {
		auditItems = append(auditItems, map[string]any{
			"session_id": item.SessionID,
			"tool":       item.Tool,
			"args":       item.Args,
			"confirmed":  item.Confirmed,
			"preview":    item.Preview,
			"result":     item.Result,
			"guard":      item.Guard,
			"created_at": item.CreatedAt,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"audit":        auditItems,
		"writes":       writes,
		"balance_cent": balance,
		"tenant_id":    tenantID,
	})
}

func (s *state) reset(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "POST required"})
		return
	}
	_ = s.database.Exec("DELETE FROM agent_audit_log").Error
	_ = s.database.Exec("DELETE FROM agent_session").Error
	s.memory.FlushAll()
	s.mu.Lock()
	s.balance = defaultBalance
	s.writes = []map[string]any{}
	s.mu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"status": "reset"})
}

func writeJSON(w http.ResponseWriter, status int, payload map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
