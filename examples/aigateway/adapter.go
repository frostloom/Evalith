// Evalith-owned adapter. The imported ai-gateway Handler is unchanged.
// Billing data is synthetic; no existing MySQL, Redis or gateway is contacted.
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

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	var input struct {
		Turns   []string `json:"turns"`
		Fixture struct {
			BalanceCent *int64 `json:"balance_cent"`
		} `json:"fixture"`
	}
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 100000)).Decode(&input); err != nil {
		return err
	}
	if len(input.Turns) == 0 || len(input.Turns) > 12 {
		return fmt.Errorf("1–12 turns required")
	}
	work := os.Getenv("EVALITH_CASE_DIR")
	if work == "" || os.Getenv("EVALITH_MODEL_URL") == "" || os.Getenv("EVALITH_MODEL_TOKEN") == "" {
		return fmt.Errorf("owned case/model configuration required")
	}
	database, err := gorm.Open(sqlite.Open(filepath.Join(work, "agent.db")), &gorm.Config{Logger: gormlogger.Default.LogMode(gormlogger.Silent)})
	if err != nil {
		return err
	}
	sqlDB, err := database.DB()
	if err != nil {
		return err
	}
	defer sqlDB.Close()
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
	st := store.NewStore(database, rdb)
	balance := int64(200000)
	if input.Fixture.BalanceCent != nil {
		balance = *input.Fixture.BalanceCent
	}
	var mu sync.Mutex
	writes := make([]map[string]any, 0)
	billing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method != "GET" {
			var body map[string]any
			_ = json.NewDecoder(io.LimitReader(r.Body, 100000)).Decode(&body)
			mu.Lock()
			writes = append(writes, map[string]any{"path": r.URL.Path, "body": body})
			mu.Unlock()
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "id": 1, "order_id": 1, "status": "paid"})
			return
		}
		switch r.URL.Path {
		case "/admin/me":
			_ = json.NewEncoder(w).Encode(store.MeView{Balance: balance, BalanceCent: balance, LedgerBalance: balance, Consistent: true, Plans: []store.Plan{}, Topups: []store.Topup{}})
		case "/admin/bills", "/admin/recharge-orders", "/portal/models":
			_ = json.NewEncoder(w).Encode(map[string]any{"items": []any{}})
		default:
			w.WriteHeader(404)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": "synthetic fixture route unavailable"})
		}
	}))
	defer billing.Close()
	model := os.Getenv("EVALITH_MODEL_NAME")
	if model == "" {
		return fmt.Errorf("explicit model required")
	}
	llm, err := agent.NewEvaluationLLMClient(os.Getenv("EVALITH_MODEL_URL"), os.Getenv("EVALITH_MODEL_TOKEN"), model, "openai", &http.Client{Timeout: 90 * time.Second, Transport: &http.Transport{Proxy: nil, MaxConnsPerHost: 1, ResponseHeaderTimeout: 85 * time.Second}}, 512)
	if err != nil {
		return err
	}
	handler := agent.NewHandler(nil, agent.NewToolbox(agent.NewAdminClientWithToken(billing.URL, "evalith-synthetic")), llm, st, rdb, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err = handler.SetRoutingMode("model"); err != nil {
		return err
	}
	handler.SetAdminAccess("evalith-owned-fixture", 42)
	turns := make([]map[string]any, 0, len(input.Turns))
	reply := ""
	for _, message := range input.Turns {
		raw, _ := json.Marshal(map[string]any{"session_id": "evalith-case", "message": message})
		request := httptest.NewRequest("POST", "http://evalith.local/chat", bytes.NewReader(raw))
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("X-Agent-Internal", "evalith-owned-fixture")
		request.Header.Set("X-Agent-Tenant", "42")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		var result map[string]any
		if err = json.Unmarshal(response.Body.Bytes(), &result); err != nil {
			return err
		}
		result["http_status"] = response.Code
		result["input"] = message
		turns = append(turns, result)
		if text, ok := result["reply"].(string); ok {
			reply = text
		}
		if response.Code != 200 {
			break
		}
	}
	var audit []store.AgentAuditLog
	if err = database.Order("id ASC").Find(&audit).Error; err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"reply": reply, "turns": turns, "writes": writes, "audit": audit, "fixture": map[string]any{"balance_cent": balance, "tenant_id": 42}, "execution": "actual ai-gateway customer-service Handler with synthetic billing and isolated SQLite/miniredis", "model": model})
}
