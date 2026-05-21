import React from 'react';

export default function OrderBook({ orders, onSelectSymbol }) {
  const getStatusBadgeClass = (status) => {
    const s = status.toUpperCase();
    if (s === 'COMPLETE') return 'trend-bull';
    if (s === 'REJECTED' || s === 'CANCELLED') return 'trend-bear';
    if (s === 'OPEN' || s === 'TRIGGER PENDING') return 'trend-neut';
    return '';
  };

  return (
    <div className="glass-panel" style={{ marginTop: '20px' }}>
      <div className="panel-header">
        <span>Zerodha Orderbook (Recent Actions)</span>
      </div>
      
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <table className="custom-table">
          <thead>
            <tr>
              <th>Order ID</th>
              <th>Symbol</th>
              <th>Type</th>
              <th>Order Type</th>
              <th>Qty</th>
              <th>Price</th>
              <th>Trigger Price</th>
              <th>Status</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 ? (
              <tr>
                <td colSpan="9" style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '20px' }}>
                  No orders found.
                </td>
              </tr>
            ) : (
              orders.map((o) => {
                const isBuy = o.transaction_type === 'BUY';
                const statusClass = getStatusBadgeClass(o.status);

                return (
                  <tr key={o.order_id}>
                    {/* Order ID */}
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>
                      {o.order_id}
                    </td>
                    
                    {/* Symbol */}
                    <td 
                      style={{ fontWeight: 700, color: 'var(--color-cyan)', cursor: 'pointer' }} 
                      onClick={() => onSelectSymbol(o.symbol)}
                      title="Click to view chart"
                    >
                      {o.symbol}
                    </td>
                    
                    {/* Type */}
                    <td 
                      className={isBuy ? 'text-up' : 'text-down'}
                      style={{ fontWeight: 700 }}
                    >
                      {o.transaction_type}
                    </td>
                    
                    {/* Order Type */}
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                      {o.order_type}
                    </td>
                    
                    {/* Qty */}
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      {o.quantity}
                    </td>
                    
                    {/* Price */}
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      {o.price > 0 ? `₹${o.price.toFixed(2)}` : '-'}
                    </td>
                    
                    {/* Trigger Price */}
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      {o.trigger_price > 0 ? `₹${o.trigger_price.toFixed(2)}` : '-'}
                    </td>
                    
                    {/* Status */}
                    <td>
                      <span className={`trend-badge ${statusClass}`} style={{ fontSize: '0.65rem' }}>
                        {o.status}
                      </span>
                    </td>
                    
                    {/* Status Message */}
                    <td style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={o.status_message}>
                      {o.status_message}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
