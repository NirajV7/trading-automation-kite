import React, { useState } from 'react';

export default function OrderBook({ orders, onSelectSymbol, onCancelOrder, onModifyOrder }) {
  const [activeSubTab, setActiveSubTab] = useState('pending'); // 'pending' or 'executed'

  // Define status lists
  const pendingStatuses = ['OPEN', 'TRIGGER PENDING', 'VALIDATION PENDING', 'PUT ORDER REQ RECEIVED'];
  
  const pendingOrders = orders.filter(o => pendingStatuses.includes(o.status.toUpperCase()));
  const executedOrders = orders.filter(o => !pendingStatuses.includes(o.status.toUpperCase()));

  const getStatusBadgeClass = (status) => {
    const s = status.toUpperCase();
    if (s === 'COMPLETE') return 'trend-bull';
    if (s === 'REJECTED' || s === 'CANCELLED') return 'trend-bear';
    if (s === 'OPEN' || s === 'TRIGGER PENDING') return 'trend-neut';
    return '';
  };

  const renderOrderRow = (o, isPending) => {
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
        
        {/* Trigger Price (Pending only) */}
        {isPending && (
          <td style={{ fontFamily: 'var(--font-mono)' }}>
            {o.trigger_price > 0 ? `₹${o.trigger_price.toFixed(2)}` : '-'}
          </td>
        )}
        
        {/* Status */}
        <td>
          <span className={`trend-badge ${statusClass}`} style={{ fontSize: '0.65rem' }}>
            {o.status}
          </span>
        </td>
        
        {/* Actions or Message */}
        {isPending ? (
          <td>
            <button 
              className="btn-action-modify"
              onClick={() => onModifyOrder(
                o.order_id, 
                o.variety || 'regular', 
                o.order_type, 
                o.quantity, 
                o.price, 
                o.trigger_price
              )}
            >
              ✏️ Modify
            </button>
            <button 
              className="btn-action-cancel"
              onClick={() => onCancelOrder(o.order_id, o.variety || 'regular')}
            >
              ❌ Cancel
            </button>
          </td>
        ) : (
          <td 
            style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} 
            title={o.status_message}
          >
            {o.status_message}
          </td>
        )}
      </tr>
    );
  };

  const activeOrdersList = activeSubTab === 'pending' ? pendingOrders : executedOrders;

  return (
    <div className="glass-panel risk-table-panel orderbook-panel">
      <div className="risk-panel-header">
        <div>
          <h2>Zerodha Orderbook</h2>
          <p>Pending and executed orders with quick modify/cancel controls.</p>
        </div>
        
        {/* Sub-tabs selector */}
        <div className="risk-subtabs">
          <button 
            className={activeSubTab === 'pending' ? 'active' : ''}
            onClick={() => setActiveSubTab('pending')}
          >
            Pending ({pendingOrders.length})
          </button>
          <button 
            className={activeSubTab === 'executed' ? 'active' : ''}
            onClick={() => setActiveSubTab('executed')}
          >
            Executed ({executedOrders.length})
          </button>
        </div>
      </div>
      
      <div className="risk-table-wrap orderbook-table-wrap">
        <table className="custom-table risk-data-table">
          <thead>
            <tr>
              <th>Order ID</th>
              <th>Symbol</th>
              <th>Type</th>
              <th>Order Type</th>
              <th>Qty</th>
              <th>Price</th>
              {activeSubTab === 'pending' && <th>Trigger Price</th>}
              <th>Status</th>
              <th>{activeSubTab === 'pending' ? 'Actions' : 'Message'}</th>
            </tr>
          </thead>
          <tbody>
            {activeOrdersList.length === 0 ? (
              <tr>
                <td 
                  colSpan={activeSubTab === 'pending' ? 9 : 8} 
                  style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '20px' }}
                >
                  <div className="risk-empty-state">
                    <strong>No {activeSubTab} orders</strong>
                    <span>{activeSubTab === 'pending' ? 'Open and trigger-pending orders will appear here.' : 'Completed, cancelled, and rejected orders will appear here.'}</span>
                  </div>
                </td>
              </tr>
            ) : (
              activeOrdersList.map((o) => renderOrderRow(o, activeSubTab === 'pending'))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
